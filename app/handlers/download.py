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
from pathlib import Path
from typing import Any

from telegram.ext import ContextTypes

from app.services import downloader as downloader_service
from app.services.access import MSG_ACCESS_DENIED, can_download
from app.services.errors import RateLimitedError, UploadError, user_message
from app.services.stats import Stats
from app.services.uploader import send_video
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
    """Saluran `notify` worker: kirim pesan antrean (kedaluwarsa) ke chat user."""
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


async def _upload_after_download(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    result,
    chat_id: int,
    settings,
) -> bool:
    """T-087: setelah download sukses, kirim video ke Telegram.

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
    """
    safe_metadata = sanitize_metadata(result.metadata or {})
    safe_title = sanitize_filename(str(safe_metadata.get("title") or ""))
    try:
        await send_video(
            bot=context.bot,
            chat_id=chat_id,
            file_path=result.path,
            title=safe_title,
            url=url,
            max_file_size_mb=settings.max_file_size_mb,
            metadata=safe_metadata,
        )
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
                result = await downloader_service.download(url, settings)
                uploaded = await _upload_after_download(context, url, result, chat_id, settings)
                # T-164 (FR-021): hanya upload yang benar-benar tersampaikan yang
                # dihitung "diproses"; kegagalan download maupun upload masuk
                # `download_failed`. Tidak ada perubahan aliran/teks di atas.
                if uploaded:
                    _stats_processed(bot_data)
                else:
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

    # ---- T-172 (FR-022): admission control SEBELUM ada pekerjaan apa pun ----
    # Tidak ada lagi spawn task per request (pola lama `_job` di-launch inline): yang dijadwalkan
    # sekarang adalah DATA (Job), bukan task baru. Jumlah task per proses tetap
    # konstan = `max_concurrent_downloads` worker (+ task ptb), itu bukti
    # anti-OOM yang diukur test banjir (T-175b).
    queue = _get_default_queue(bot_data, settings)
    _ensure_workers(bot_data, settings)

    counter = _task_counter_of(bot_data)
    if counter is not None:
        counter[0] += 1
    try:
        queue.put_nowait(build_job(update, url, context))
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
    if queue.qsize() > 1:
        await update.message.reply_text(f"{ACK_TEXT} (antrean: {queue.qsize()})")
    else:
        await update.message.reply_text(ACK_TEXT)
