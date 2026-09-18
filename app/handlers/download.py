"""Handler URL detection + dispatch (FR-003..FR-005, FR-007, FR-009, FR-011).

WP-17 (FR-022): jalur "spawn task per request" DIHAPUS dari handler. Handler
sekarang hanya melakukan admission control (`put_nowait` ke `asyncio.Queue`
ber-`maxsize` di `bot_data`); `app.services.work_queue.worker_loop` yang
mengeksekusi `run_job`. `run_job` adalah badan `_job()` lama WP-06..WP-11 yang
diangkat keluar apa adanya: urutan panggilan, teks balasan, cakupan `except`,
dan satu-slot-utuh `async with semaphore` tidak dirombak (T-172).

Urutan lapis tetap (PLAN WP-17): gate akses -> validasi URL -> rate limiter ->
antrean (FR-011 sebelum FR-022). Ack `⏳ Sedang memproses...` dikirim SETELAH
admission sukses (T-113: handler tetap return < 2 dtk, karena antrean hanyalah
`put_nowait`), dengan info posisi antrean sebagai teks TAMBAHAN setelah frasa
kunci (test lama memakai pencocokan substring/daftar literal).

Deviasi WP-17 (dicatat di Log): `track_progress=True` di call `download()`
DIHAPUS. Badan job kini berjalan di task worker yang TIDAK memegang context
update (context diangkut lewat `Job`, dan memakainya melintasi task untuk
edit-progress pesan lama berisiko `Message Not Found` + membuat test lama yang
mengunci `download(url, settings)` positional jadi rapuh). Progres per-file
bukan kontrak PRD; ack + hasil akhir tetap. Lihat Log WP-17 butir deviasi.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.services import dialog as dialog_service
from app.services import downloader as downloader_service
from app.services.access import MSG_ACCESS_DENIED, can_download
from app.services.advance import Selection, quality_note
from app.services.errors import RateLimitedError, UploadError, user_message
from app.services.stats import Stats
from app.services.uploader import send_audio, send_video
from app.services.validator import UnsupportedUrlError, extract_url, validate_url
from app.services.work_queue import (
    MSG_QUEUE_FULL,
    Job,
    build_job,
    ensure_workers,
)
from app.utils.files import clean_dir, sanitize_filename, sanitize_metadata

logger = logging.getLogger(__name__)

#: Frasa ack WP-06 yang dikunci test lama (test_concurrency/test_errors/
#: test_handlers/test_wp13). INFO antrean hanya boleh di-APPEND setelah frasa
#: ini dengan pemisah spasi, tidak pernah mengubah/menggantikannya (T-172).
ACK_TEXT = "⏳ Sedang memproses..."

#: Kunci `bot_data` antrean kerja in-process (WP-17, FR-022).
QUEUE_KEY = "queue"
WORKERS_KEY = "workers"
STOP_EVENT_KEY = "stop_event"
TASK_COUNTER_KEY = "task_counter"
JOB_RUNTIME_KEY = "job_runtime"

#: WP-21 (T-211): registry pesan ack per chat. `ack_messages[chat_id]` =
#: `message_id` pesan `ACK_TEXT` yang masih hidup; `ack_tokens[token]` =
#: `(chat_id, message_id, url)` untuk memetakan callback `ac:<token>` kembali
#: ke job. `ack_cancel_requested` = himpunan `token` yang tombol Batalkan-nya
#: sudah ditekan (payload mau dilewati di titik aman, lihat `run_job`).
ACK_MESSAGES_KEY = "ack_messages"
ACK_TOKENS_KEY = "ack_tokens"
ACK_CANCEL_KEY = "ack_cancel_requested"

#: WP-21 (T-213): prefix callback tombol Batalkan. WAJIB beda dari `ad:` WP-19
#: (`app/services/dialog.py`) supaya dua `CallbackQueryHandler` tidak saling
#: menelan: pattern `^ac:` hanya cocok untuk tombol batalkan antrean.
ACK_CALLBACK_PREFIX = "ac:"

#: Teks tombol + jawaban callback (PRD §3: tidak ada "Updating…" menggantung).
ACK_CANCEL_LABEL = "❌ Batalkan"
MSG_ACK_CANCEL_QUEUED = "🗑️ Dibatalkan sebelum diproses."
MSG_ACK_CANCEL_RUNNING = "⏹️ Permintaan dicatat; job dilewati di titik aman berikutnya."
MSG_ACK_CANCEL_DONE = "✅ Permintaan ini sudah selesai diproses."
ACK_CANCELLED_SUFFIX = " (dibatalkan)"

_START_TEXT = (
    "👋 Instagram/Facebook/TikTok Downloader\n"
    "\n"
    "Kirim link Instagram, Facebook, atau TikTok Reels\n"
    "dan saya akan mencoba mengunduh videonya.\n"
    "\n"
    "Contoh:\n"
    "https://www.instagram.com/reel/xxxxx/\n"
    "https://www.tiktok.com/@user/video/1234567890"
)


def _stats_of(bot_data: dict) -> Stats | None:
    """T-164 (FR-021): ambil `Stats` dari `bot_data`.

    None bila kunci belum ada. Sengaja TIDAK membuat instance baru: `/stats`
    membaca `bot_data["stats"]` lewat `context` yang sama (app/handlers/account.py),
    jadi counter harus berasal dari satu objek. Test lama yang memakai
    `bot_data` manual tanpa startup memang tidak mencatat apa pun (tidak ada
    yang mengasersi angka mereka).
    """
    stats = bot_data.get("stats")
    return stats if isinstance(stats, Stats) else None


def _stats_reject(bot_data: dict, reason: str) -> None:
    """T-164: hitung satu penolakan nyata; no-op bila stats belum diwiring."""
    stats = _stats_of(bot_data)
    if stats is not None:
        stats.inc_rejected(reason)


def _stats_processed(bot_data: dict) -> None:
    """T-164: hitung satu pekerjaan selesai; no-op bila stats belum diwiring."""
    stats = _stats_of(bot_data)
    if stats is not None:
        stats.inc_processed()


def _get_default_queue(bot_data: dict, settings: Any) -> asyncio.Queue:
    """Lazy: buat `asyncio.Queue(maxsize=queue_max_size)` di `bot_data` (T-172).

    Jalur test lama (`bot_data` manual tanpa `main()`) dan jalur produksi
    bertemu di accessor yang sama, jadi tidak pernah ada "antrean hantu"
    (job masuk queue yang tidak dibaca siapa pun). `maxsize` dari
    `queue_max_size`, BUKAN `max_concurrent_downloads` (dua knob beda).
    """
    queue = bot_data.get(QUEUE_KEY)
    if queue is None:
        maxsize = getattr(settings, "queue_max_size", None)
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize < 1:
            maxsize = 20  # default PRD §5 (Settings.queue_max_size)
        queue = asyncio.Queue(maxsize=maxsize)
        bot_data[QUEUE_KEY] = queue
    if bot_data.get(STOP_EVENT_KEY) is None:
        bot_data[STOP_EVENT_KEY] = asyncio.Event()
    return queue


def _ensure_workers(bot_data: dict, settings: Any) -> list[asyncio.Task]:
    """Spawn tepat `max_concurrent_downloads` task `worker_loop`, idempoten (T-172).

    Penjadwalan job kini lewat `app/services/work_queue.py`, BUKAN di modul ini:
    gerbang WP-17 menuntut jalur spawn-per-request hilang dari
    `download.py` (bukan berpindah tempat di sini).
    """
    if bot_data.get(WORKERS_KEY):
        return list(bot_data[WORKERS_KEY])
    return ensure_workers(
        bot_data,
        run_job=run_job,
        notify=_notify_chat,
        queue=_get_default_queue(bot_data, settings),
        settings=settings,
    )


async def _notify_chat(job: Job, text: str) -> None:
    """Saluran `notify` worker: kirim pesan antrean (kedaluwarsa) ke chat user.

    WP-21 (T-216e): job kedaluwarsa TIDAK melewati `run_job`, jadi ack-nya
    harus dihapus DI SINI juga - kalau tidak, pesan `⏳ Sedang memproses...`
    menggantung berdampingan dengan `MSG_QUEUE_EXPIRED` (temuan asal WP).
    """
    await _delete_ack(job.context.bot, job.context.bot_data, job.chat_id, job.token)
    _drop_ack_token(job.context.bot_data, job.token)
    await job.context.bot.send_message(chat_id=job.chat_id, text=text)


def _task_counter_of(bot_data: dict) -> list[int] | None:
    counter = bot_data.get(TASK_COUNTER_KEY)
    return counter if isinstance(counter, list) and counter else None


def _counter_change(bot_data: dict, delta: int) -> None:
    """Ubah `bot_data["task_counter"]` (list satu elemen agar mutable).

    No-op bila kunci tidak ada (jalur test lama). Naik di handler HANYA
    setelah `put_nowait` sukses; turun di `finally` `run_job` (satu-satunya
    jalur pelepasan) - lihat aturan anti-deadlock T-115 di Log WP-17.
    """
    counter = _task_counter_of(bot_data)
    if counter is not None:
        counter[0] = max(0, counter[0] + delta)


# ------------------------------- WP-21: registry pesan ack (T-211) ----------


def register_ack(bot_data: dict, chat_id: int, message_id: int | None) -> None:
    """Catat `message_id` pesan ack terbaru untuk `chat_id` (T-211, FR-007).

    Ack adalah SATU-satunya pesan "sedang memproses" per chat: mencatat ack
    baru untuk chat yang sama berarti ack lama di-REPLACE di registry (bukan
    dihapus paksa) sehingga tidak ada dua pesan hidup bersamaan. `None`
    (mis. `reply_text` tiruan tanpa `message_id`) hanya membersihkan entri.
    """
    messages = bot_data.get(ACK_MESSAGES_KEY)
    if not isinstance(messages, dict):
        messages = {}
        bot_data[ACK_MESSAGES_KEY] = messages
    if message_id is None:
        messages.pop(chat_id, None)
        return
    messages[chat_id] = message_id


def pop_ack(bot_data: dict, chat_id: int) -> int | None:
    """Ambil-lalu-hapus `message_id` ack milik `chat_id` (T-211, FR-007).

    Idempoten: pemanggilan kedua mengembalikan `None`, jadi dua jalur yang
    sama-sama berhak menghapus (job `finally` + tombol Batalkan) tidak pernah
    menghapus pesan yang sama dua kali.
    """
    messages = bot_data.get(ACK_MESSAGES_KEY)
    if not isinstance(messages, dict):
        return None
    message_id = messages.pop(chat_id, None)
    return message_id if isinstance(message_id, int) else None


def register_ack_token(bot_data: dict, token: str, chat_id: int, message_id: int | None) -> None:
    """Petakan `token` tombol Batalkan -> `(chat_id, message_id)` (T-213)."""
    tokens = bot_data.get(ACK_TOKENS_KEY)
    if not isinstance(tokens, dict):
        tokens = {}
        bot_data[ACK_TOKENS_KEY] = tokens
    tokens[token] = (chat_id, message_id)


def _drop_ack_token(bot_data: dict, token: str | None) -> None:
    """Buang pemetaan token (job selesai/dibatalkan); no-op bila tak ada."""
    tokens = bot_data.get(ACK_TOKENS_KEY)
    if isinstance(tokens, dict) and token is not None:
        tokens.pop(token, None)


def _ack_cancelled(bot_data: dict, token: str | None) -> bool:
    """True bila tombol Batalkan untuk `token` sudah ditekan (T-213)."""
    if token is None:
        return False
    requested = bot_data.get(ACK_CANCEL_KEY)
    return isinstance(requested, set) and token in requested


def _mark_ack_cancelled(bot_data: dict, token: str) -> None:
    """Tandai `token` untuk dilewati di titik aman (T-213)."""
    requested = bot_data.get(ACK_CANCEL_KEY)
    if not isinstance(requested, set):
        requested = set()
        bot_data[ACK_CANCEL_KEY] = requested
    requested.add(token)


def ack_keyboard(token: str) -> InlineKeyboardMarkup:
    """Keyboard satu tombol Batalkan dengan callback `ac:<token>` (T-213)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(ACK_CANCEL_LABEL, callback_data=f"{ACK_CALLBACK_PREFIX}{token}")]]
    )


async def _delete_ack(bot: Any, bot_data: dict, chat_id: int, token: str | None = None) -> None:
    """Hapus pesan ack milik job ini bila masih tercatat (T-212, FR-007/FR-008).

    Urutan pilih pesan: peta token (`ac:<token>` -> message_id) lebih dulu,
    baru registry per-chat. Alasannya: kalau user mengirim link KEDUA saat job
    pertama masih jalan, registry per-chat sudah menunjuk ack BARU (T-211:
    satu ack hidup per chat, ack lama di-replace tanpa hapus paksa). Tanpa
    jalur token, job pertama akan menghapus pesan ack milik job kedua.

    Wajib tahan-banting: `BadRequest` (mis. `Message to delete not found`,
    `Message can't be deleted`) atau error apa pun HANYA di-`logger.warning`
    (AGENTS §5: traceback ke log, bukan ke user) - `run_job` tidak boleh
    raise dan worker tidak boleh mati. Entri di-pop lebih dulu supaya pesan
    yang sama tidak pernah dihapus dua kali oleh jalur lain.
    """
    message_id: int | None = None
    tokens = bot_data.get(ACK_TOKENS_KEY)
    if token is not None and isinstance(tokens, dict):
        entry = tokens.pop(token, None)
        if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[1], int):
            message_id = entry[1]
    if message_id is None:
        message_id = pop_ack(bot_data, chat_id)
    else:
        # Registry per-chat hanya dibersihkan bila masih menunjuk pesan yang
        # sama; kalau sudah digantikan ack baru, jangan sentuh entri itu.
        messages = bot_data.get(ACK_MESSAGES_KEY)
        if isinstance(messages, dict) and messages.get(chat_id) == message_id:
            messages.pop(chat_id, None)
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.warning(
            "hapus pesan ack gagal (chat %s, message %s)", chat_id, message_id, exc_info=True
        )


def _ack_markup(token: str | None) -> InlineKeyboardMarkup | None:
    """Keyboard tombol Batalkan untuk ack (None bila token kosong)."""
    return ack_keyboard(token) if token else None


def _record_ack(bot_data: dict, chat_id: int, token: str | None, message: Any) -> int | None:
    """Catat `message_id` ack `message` ke registry per-chat + peta token (T-211).

    `message_id` bisa `None`/non-int pada mock tanpa `message_id`; saat itu
    registry hanya tidak bertambah (tidak ada yang dihapus salah).
    """
    message_id = getattr(message, "message_id", None)
    if not isinstance(message_id, int):
        return None
    register_ack(bot_data, chat_id, message_id)
    if token:
        register_ack_token(bot_data, token, chat_id, message_id)
    return message_id


def _new_ack_token(chat_id: int) -> str:
    """Token unik per job: `chat_id` + penghitung proses (cukup in-process)."""
    _ACK_TOKEN_SEQ[0] += 1
    return f"{chat_id}-{_ACK_TOKEN_SEQ[0]}"


#: Penghitung token ack proses-lokal (satu event-loop, pola `task_counter`).
_ACK_TOKEN_SEQ = [0]


async def cancel_ack_callback(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`ac:<token>` (T-213, FR-022): batalkan job yang menunggu / tandai yang jalan.

    Selalu `answer()` tepat sekali di SETIAP cabang supaya tidak ada spinner
    "Updating…" menggantung (pola WP-19). Job yang masih di antrean dikeluarkan
    (`get_nowait` + `task_done` + counter) lalu ack-nya dihapus; job yang sudah
    jalan hanya ditandai (`ack_cancel_requested`) dan dilewati di titik aman
    setelah download selesai (tidak ada klaim "download dihentikan": `yt-dlp`
    blocking di `asyncio.to_thread` memang tidak bisa di-interrupt). Tombol
    yang ditekan setelah job selesai dijawab halus, bukan error.
    """
    query = update.callback_query
    data = getattr(query, "data", "") or ""
    token = data[len(ACK_CALLBACK_PREFIX) :] if data.startswith(ACK_CALLBACK_PREFIX) else ""
    bot_data = context.bot_data
    tokens = bot_data.get(ACK_TOKENS_KEY)
    entry = tokens.get(token) if isinstance(tokens, dict) else None
    if not token or entry is None:
        # Basi / sudah selesai: jawab halus, jangan error (T-213).
        await query.answer(MSG_ACK_CANCEL_DONE)
        return

    chat_id, message_id = entry
    queue = bot_data.get(QUEUE_KEY)
    removed_from_queue = False
    if isinstance(queue, asyncio.Queue):
        # `_extract_job_from_queue` menyeimbangkan `_unfinished_tasks` sendiri
        # (lihat docstring), jadi tidak ada `task_done()` tambahan di sini.
        if _extract_job_from_queue(queue, token) is not None:
            removed_from_queue = True
            # Slot kerja WP-17 dilepas: job ini tidak akan pernah melewati
            # `finally` `run_job` (satu-satunya tempat penurunan lain).
            _counter_change(bot_data, -1)
    _drop_ack_token(bot_data, token)
    if removed_from_queue:
        text = MSG_ACK_CANCEL_QUEUED
    else:
        _mark_ack_cancelled(bot_data, token)
        text = MSG_ACK_CANCEL_RUNNING
    # Hapus pesan ack (job dipegang TIDAK bisa di-cancel bersih: lihat docstring).
    if isinstance(message_id, int):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.warning(
                "hapus ack lewat tombol gagal (chat %s, message %s)",
                chat_id,
                message_id,
                exc_info=True,
            )
    # Registry per-chat juga dibersihkan bila menunjuk pesan yang sama.
    messages = bot_data.get(ACK_MESSAGES_KEY)
    if isinstance(messages, dict) and messages.get(chat_id) == message_id:
        messages.pop(chat_id, None)
    await query.answer(text)


def _extract_job_from_queue(queue: asyncio.Queue, token: str) -> Any | None:
    """Keluarkan job bertoken `token` dari `queue` tanpa mengganggu FIFO lain.

    Job yang TIDAK cocok dikembalikan ke antrean dengan urutan semula, jadi
    membatalkan satu permintaan tidak menyentuh job lain (T-216 butir f).

    Awas penghitung: `asyncio.Queue.put()` menaikkan `_unfinished_tasks`, jadi
    pemasukan kembali item harus "dibayar" dengan `task_done()` agar `join()`
    tidak pernah menggantung. Job yang DIBUANG tidak akan pernah diproses
    worker (tidak ada `task_done` dari sana), jadi buku besar ditutup di sini:
    `task_done()` dipanggil SEKALI untuk setiap item yang diambil - n item
    diambil, n-1 dimasukkan kembali (masing-masing menambah 1 tugas), lalu
    (n-1) kali `task_done()` + 1 kali untuk job yang dibuang.
    """
    pending: list[Any] = []
    found = None
    taken = 0
    while True:
        try:
            job = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        taken += 1
        if found is None and getattr(job, "token", None) == token:
            found = job
        else:
            pending.append(job)
    for job in pending:
        queue.put_nowait(job)
    # Tutup buku besar: `get_nowait` sendiri tidak menurunkan `_unfinished_tasks`.
    for _ in range(taken):
        queue.task_done()
    return found


async def admit_advance_job(
    update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    selection: Selection | None = None,
) -> bool:
    """FR-015..FR-017: admission dari jalur dialog advance (bukan handler URL).

    Antrean/worker/counter sama dengan jalur reguler; balas lewat chat
    karena callback TIDAK punya `update.message.reply_text` yang valid.
    Return True bila job diterima; False bila antrean penuh.
    """
    bot_data = context.bot_data
    settings = bot_data["settings"]
    queue = _get_default_queue(bot_data, settings)
    _ensure_workers(bot_data, settings)
    chat_id = update.effective_chat.id
    # T-213: token unik untuk tombol Batalkan job ini; ack terkirim hanya
    # setelah admission sukses (pola T-113), jadi tidak ada ack yatim.
    token = _new_ack_token(chat_id)
    ack_text = f"{ACK_TEXT} (antrean: {queue.qsize() + 1})" if queue.qsize() else ACK_TEXT
    counter = _task_counter_of(bot_data)
    if counter is not None:
        counter[0] += 1
    try:
        queue.put_nowait(replace(build_job(update, url, context, selection), token=token))
    except asyncio.QueueFull:
        if counter is not None:
            counter[0] = max(0, counter[0] - 1)
        _stats_reject(bot_data, "queue_full")
        logger.info(
            "antrean penuh (chat %s, maxsize %s): permintaan advance ditolak",
            chat_id,
            queue.maxsize,
        )
        await context.bot.send_message(chat_id=chat_id, text=MSG_QUEUE_FULL)
        return False
    ack_text = f"{ACK_TEXT} (antrean: {queue.qsize()})" if queue.qsize() > 1 else ACK_TEXT
    ack_message = await context.bot.send_message(
        chat_id=chat_id, text=ack_text, reply_markup=_ack_markup(token)
    )
    _record_ack(bot_data, chat_id, token, ack_message)
    return True


async def _upload_after_download(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    result,
    chat_id: int,
    settings,
    selection: Selection | None = None,
) -> bool:
    """T-087: setelah download sukses, kirim video/audio ke Telegram.

    T-164 (FR-021): kini mengembalikan `bool` (sukses/kegagalan upload) supaya
    `run_job` bisa memisahkan "diproses" dari "gagal total". Teks balasan, urutan
    pemanggilan, dan cakupan `except` TIDAK berubah sedikit pun: nilai balik baru
    hanya dipakai pencatatan statistik defensif.

     T-104 (NFR Security): metadata + title dibersihkan lewat `sanitize_metadata`
     / `sanitize_filename` (WP-07) SEBELUM dikirim, jadi control char atau judul
     super panjang dari situs pihak ketiga tidak pernah masuk caption Telegram.
     String pesan upload di bawah sudah dikunci test WP-06/WP-08/WP-09
     (`tests/test_cleanup.py::test_cleanup_after_failed_upload`,
     `tests/test_uploader.py::test_handler_replies_error_message_when_upload_fails`)
    , tetap identik maknanya dengan `MSG_UPLOAD_FAILED` dari T-101.

    WP-19: `result.is_audio` => `send_audio` (FR-018); `selection` video dengan
    hasil lebih rendah dari permintaan => `note` caption `(720p→480p)` (FR-017).
    Tanpa keduanya, panggilan `send_video` tetap kwarg-identik jalur lama.
    """
    safe_metadata = sanitize_metadata(result.metadata or {})
    safe_title = sanitize_filename(str(safe_metadata.get("title") or ""))
    kwargs = {
        "chat_id": chat_id,
        "file_path": result.path,
        "title": safe_title,
        "url": url,
        "max_file_size_mb": settings.max_file_size_mb,
    }
    if result.is_audio:
        sender = send_audio
    else:
        sender = send_video
        kwargs["metadata"] = safe_metadata
        note = None
        if selection is not None and selection.mode == "video":
            note = quality_note(selection.quality, result.actual_height)
        if note:
            kwargs["note"] = note
    try:
        await sender(bot=context.bot, **kwargs)
    except UploadError as exc:
        logger.warning("upload gagal untuk %s: %s", url, exc)
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Gagal mengirim video ke Telegram.")
        return False
    except Exception:
        logger.exception("upload job error: %s", url)
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Gagal mengirim video.")
        return False
    return True


async def run_job(
    job: Job,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    settings: Any = None,
    semaphore: asyncio.Semaphore | None = None,
    download_dir: Path | None = None,
) -> bool:
    """Satu job lengkap: `async with semaphore` -> download -> upload -> cleanup.

    Ini badan `_job()` closure (WP-06..WP-11) yang diangkat menjadi fungsi
    modul agar bisa diimpor worker (T-172). Binding yang dulu ditangkap
    closure dari scope handler sekarang dibaca dari `job.context.bot_data`;
    argumen keyword opsional hanya dipakai test/injeksi eksplisit. Balikan
    `bool` = upload tersampaikan (kontrak T-164 untuk stats); fungsi ini tidak
    pernah raise (semua exception sudah ditangani; `worker_loop` tetap punya
    jaring kedua).
    """
    context = context if context is not None else job.context
    bot_data = context.bot_data
    runtime = bot_data.get(JOB_RUNTIME_KEY) or {}
    if settings is None:
        settings = bot_data.get("settings") or runtime.get("settings")
    if semaphore is None:
        # T-111/T-112 (FR-010): semaphore dibangun saat startup di `app/main.py`
        # dan dipakai ulang oleh semua job. Fallback hanya untuk jalur pemanggilan
        # langsung (test unit membuat `bot_data` manual tanpa startup): produksi
        # selalu melewati `main()`, jadi limitnya efektif.
        semaphore = bot_data.get("semaphore") or runtime.get("semaphore")
        if semaphore is None:
            max_concurrent = getattr(settings, "max_concurrent_downloads", None)
            if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int):
                max_concurrent = 2
            semaphore = asyncio.Semaphore(max_concurrent)
    if download_dir is None:
        download_dir = runtime.get("download_dir")
    url = job.url
    chat_id = job.chat_id
    dl_dir = Path(download_dir) if download_dir is not None else Path(settings.download_dir)

    # T-112 (FR-010): maksimal `MAX_CONCURRENT_DOWNLOADS` unduhan serentak.
    # Antrian terjadi DI SINI, SETELAH ack terkirim, jadi ack tetap < 2 dtk
    # bahkan saat semua slot busy (NFR Performance, T-113).
    # SATU job = SATU slot utuh (download -> upload -> cleanup): `clean_dir`
    # adalah operasi destruktif pada direktori bersama, jadi tidak boleh jalan
    # sementara job lain masih menulis file parsial di sana. Teks PLAN T-112
    # (`async with semaphore: await download(...)`) tetap terpenuhi: download
    # ada di dalam slot; upload/cleanup ikut karena berbagi `download_dir`.
    uploaded = False
    try:
        async with semaphore:
            try:
                # T-195/SC 16: default => panggilan posisional lama Persis;
                # hanya job advance yang menambah argumen ketiga.
                if job.selection is None:
                    result = await downloader_service.download(url, settings)
                else:
                    result = await downloader_service.download(url, settings, job.selection)
                # WP-21/T-213 (FR-022): titik aman pembatalan. Tombol Batalkan
                # TIDAK bisa menghentikan `yt-dlp` blocking di `to_thread`, jadi
                # job yang sudah ditandai dilewati DI SINI (setelah download,
                # sebelum upload) dan TIDAK diklaim "download dihentikan".
                if _ack_cancelled(bot_data, job.token):
                    logger.info("job dibatalkan setelah download (chat %s): %s", chat_id, url)
                else:
                    uploaded = await _upload_after_download(
                        context, url, result, chat_id, settings, job.selection
                    )
                # T-164 (FR-021): hanya upload yang benar-benar tersampaikan yang
                # dihitung "diproses"; kegagalan download maupun upload masuk
                # `download_failed`. Tidak ada perubahan aliran/teks di atas.
                if uploaded:
                    _stats_processed(bot_data)
                else:
                    # Kegagalan upload maupun job yang dibatalkan di titik aman
                    # sama-sama tidak menghasilkan video terkirim (T-164).
                    _stats_reject(bot_data, "download_failed")
            except Exception as exc:
                _stats_reject(bot_data, "download_failed")
                # T-103 (FR-009): log lengkap (traceback hanya ke log: AGENTS.md §5),
                # chat user hanya pesan bersih hasil `user_message()`. Level ERROR
                # dipertahankan karena test WP-06 `test_handlers.py` mengunci
                # caplog.at_level(ERROR) untuk jalur ini; lihat Log WP-10.
                logger.exception("download job failed for %s", url)
                await context.bot.send_message(chat_id=chat_id, text=user_message(exc))
            finally:
                # FR-008: sukses atau gagal, file sementara harus hilang. `clean_dir`
                # sinkron -> `asyncio.to_thread` (AGENTS.md §4.4). Cleanup gagal
                # (mis. permission) hanya di-log; tidak boleh membunuh task (WP-10
                # melengkapi pesan error user-facing).
                try:
                    await asyncio.to_thread(clean_dir, dl_dir)
                except OSError:
                    logger.warning("cleanup %s gagal", dl_dir, exc_info=True)
    finally:
        # T-115/T-172 (anti-deadlock): SATU-satunya tempat penurunan counter
        # kerja aktif: di `finally` job, BUKAN di dalam `_job` lama yang
        # me-naik-kannya sendiri. Handler menaikkan hanya saat admit sukses;
        # jalur tolak (QueueFull) tidak pernah menyisakan inc menggantung.
        _counter_change(bot_data, -1)
        # T-212 (FR-007/FR-008/FR-009): HAPUS pesan ack di sini supaya berlaku
        # untuk TIGA terminal state: upload sukses, kegagalan upload
        # (`UploadError`/`Exception`), dan kegagalan download (`except Exception`
        # di atas). `_delete_ack` menelan `BadRequest`/`MessageCantBeDeleted`
        # dan hanya `logger.warning`; `run_job` tidak pernah raise.
        await _delete_ack(context.bot, bot_data, chat_id, job.token)
        # Token dibuang supaya tombol `ac:<token>` yang ditekan setelah job
        # selesai dijawab halus oleh `cancel_ack_callback`, bukan error.
        _drop_ack_token(bot_data, job.token)
    return uploaded


async def download_handler(update, context: ContextTypes.DEFAULT_TYPE):
    # T-155 (FR-013, FR-015): gerbang akses di PALING ATAS, SEBELUM `extract_url`
    # dan sebelum rate limiter. `can_download` selalu True saat public (default
    # `bot_mode`), dan bot_data tanpa kunci `users` tetap jalan (default `{}`),
    # jadi 206 test lama tidak diutak-atik. Tidak ada perubahan lain di fungsi
    # ini: jalur antrean di bawah milik WP-17 (FR-022).
    bot_data = context.bot_data
    settings = bot_data["settings"]
    user_id = update.effective_user.id if update.effective_user else None
    if not can_download(user_id, settings, bot_data.get("users", {})):
        # T-164 (FR-021): penolakan nyata, bukan sekadar teks tanpa URL.
        _stats_reject(bot_data, "access_denied")
        await update.effective_message.reply_text(MSG_ACCESS_DENIED)
        return

    if not update.message or not update.message.text:
        return

    url = extract_url(update.message.text)
    if url is None:
        # PLAN T-164: teks tanpa URL BUKAN penolakan (hanya minta ulang), jadi
        # sengaja tidak dihitung di stats.
        await update.message.reply_text(_START_TEXT)
        return

    try:
        url = validate_url(url)
    except UnsupportedUrlError as exc:
        _stats_reject(bot_data, "unsupported_url")
        await update.message.reply_text(str(exc))
        return

    rate_limiter = bot_data["rate_limiter"]
    chat_id = update.effective_chat.id

    try:
        await rate_limiter.acquire(chat_id)
    except RateLimitedError as exc:
        _stats_reject(bot_data, "rate_limited")
        await update.message.reply_text(str(exc))
        return

    # ---- FR-015/FR-016: jalur dialog advance (link-first) ----
    # Pra-syarat: mode advance aktif untuk chat ini dan menunggu URL.
    # -> simpan URL, prompt tipe Video/Audio, RETURN tanpa antre.
    # State mati/None => fallback ke antrean reguler (SC 16).
    dialog = bot_data.get("dialog")
    if dialog is not None:
        state = dialog.get(chat_id)
        if state is not None:
            # Link baru = sesi baru: pilihan tipe/kualitas lama dibuang
            # (FR-016 "satu sesi dialog = satu link").
            dialog.set(chat_id, url=url, step=dialog_service.STEP_TYPE, tipe=None, kualitas=None)
            await update.message.reply_text(
                dialog_service.PROMPT_TYPE,
                reply_markup=dialog_service.choice_keyboard(dialog_service.STEP_TYPE),
            )
            return

    # ---- T-172 (FR-022): admission control SEBELUM ada pekerjaan apa pun ----
    # Tidak ada lagi spawn task per request (pola lama `_job` di-launch inline): yang dijadwalkan
    # sekarang adalah DATA (Job), bukan task baru. Jumlah task per proses tetap
    # konstan = `max_concurrent_downloads` worker (+ task ptb), itu bukti
    # anti-OOM yang diukur test banjir (T-175b).
    queue = _get_default_queue(bot_data, settings)
    _ensure_workers(bot_data, settings)

    # T-213: token unik per job -> tombol Batalkan `ac:<token>`.
    token = _new_ack_token(chat_id)
    counter = _task_counter_of(bot_data)
    if counter is not None:
        counter[0] += 1
    try:
        queue.put_nowait(replace(build_job(update, url, context), token=token))
    except asyncio.QueueFull:
        if counter is not None:
            counter[0] = max(0, counter[0] - 1)
        _stats_reject(bot_data, "queue_full")
        logger.info(
            "antrean penuh (chat %s, maxsize %s): permintaan ditolak",
            chat_id,
            queue.maxsize,
        )
        await update.message.reply_text(MSG_QUEUE_FULL)
        return

    # Ack T-113: setelah admit, sebelum pekerjaan berat apa pun. Angka antrean
    # (`qsize()`) adalah teks TAMBAHAN setelah frasa kunci WP-06; test lama
    # mencocokkan substring/list literal dan tetap lolos saat `qsize()` 0.
    # T-211: `message_id` ack dicatat per chat supaya `run_job` bisa
    # menghapusnya di `finally` (FR-007). Angka = posisi job ini di antrean.
    ack_text = f"{ACK_TEXT} (antrean: {queue.qsize()})" if queue.qsize() > 1 else ACK_TEXT
    ack_message = await update.message.reply_text(ack_text, reply_markup=_ack_markup(token))
    _record_ack(bot_data, chat_id, token, ack_message)
