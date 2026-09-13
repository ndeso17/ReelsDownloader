"""Handler URL detection + dispatch (FR-003..FR-005, FR-007, FR-009, FR-011)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram.ext import ContextTypes

from app.services import downloader as downloader_service
from app.services.access import MSG_ACCESS_DENIED, can_download
from app.services.errors import RateLimitedError, UploadError, user_message
from app.services.stats import Stats
from app.services.uploader import send_video
from app.services.validator import UnsupportedUrlError, extract_url, validate_url
from app.utils.files import clean_dir, sanitize_filename, sanitize_metadata

logger = logging.getLogger(__name__)

#: FR-001: minta URL ketika pengguna mengirim teks tanpa URL yang valid.
_START_TEXT = (
    "👋 Instagram/Facebook Downloader\n"
    "\n"
    "Kirim link Instagram atau Facebook Reels\n"
    "dan saya akan mencoba mengunduh videonya.\n"
    "\n"
    "Contoh:\n"
    "https://www.instagram.com/reel/xxxxx/"
)


def _stats_of(bot_data: dict) -> Stats | None:
    """T-164 (FR-021): ambil stats secara defensif.

    `bot_data` buatan test lama WP-06..WP-10 tidak punya kunci `stats`, jadi
    `None` berarti pencatatan dilewati (bukan error).
    """
    return bot_data.get("stats")


def _stats_reject(bot_data: dict, reason: str) -> None:
    """T-164: hitung satu penolakan nyata; no-op bila stats belum diwiring."""
    stats = _stats_of(bot_data)
    if stats:
        stats.inc_rejected(reason)


def _stats_processed(bot_data: dict) -> None:
    """T-164: hitung satu permintaan yang selesai diunggah; no-op bila tak ada stats."""
    stats = _stats_of(bot_data)
    if stats:
        stats.inc_processed()


async def _upload_after_download(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    result: downloader_service.DownloadResult,
    chat_id: int,
    settings,
) -> bool:
    """T-087: setelah download sukses, kirim video ke Telegram.

    T-164 (FR-021): kini mengembalikan `bool` (sukses/kegagalan upload) supaya
    `_job` bisa memisahkan "diproses" dari "gagal total". Teks balasan, urutan
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


async def download_handler(update, context: ContextTypes.DEFAULT_TYPE):
    # T-155 (FR-013, FR-015): gerbang akses di PALING ATAS, SEBELUM `extract_url`
    # dan sebelum rate limiter. `can_download` selalu True saat public (default
    # `bot_mode`), dan bot_data tanpa kunci `users` tetap jalan (default `{}`),
    # jadi 206 test lama tidak diutak-atik. Tidak ada perubahan lain di fungsi
    # ini: jalur `create_task` di bawah tetap milik WP-06..WP-10 (antrean = WP-17).
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

    await update.message.reply_text("⏳ Sedang memproses...")

    # T-111/T-112 (FR-010): semaphore dibangun saat startup di `app/main.py` dan
    # dipakai ulang oleh semua job. `.get()` + fallback hanya untuk jalur pemanggilan
    # langsung (test unit WP-06/WP-08/WP-09/WP-10 membuat `bot_data` manual tanpa
    # startup): produksi selalu melewati `main()`, jadi limitnya efektif.
    semaphore: asyncio.Semaphore = bot_data.get("semaphore") or asyncio.Semaphore(
        settings.max_concurrent_downloads
    )

    async def _job():
        dl_dir = Path(settings.download_dir)
        # T-112 (FR-010): maksimal `MAX_CONCURRENT_DOWNLOADS` unduhan serentak.
        # Antrian terjadi DI SINI, SETELAH ack terkirim, jadi ack tetap < 2 dtk
        # bahkan saat semua slot busy (NFR Performance, T-113).
        # SATU job = SATU slot utuh (download -> upload -> cleanup): `clean_dir`
        # adalah operasi destruktif pada direktori bersama, jadi tidak boleh jalan
        # sementara job lain masih menulis file parsial di sana. Teks PLAN T-112
        # (`async with semaphore: await download(...)`) tetap terpenuhi: download
        # ada di dalam slot; upload/cleanup ikut karena berbagi `download_dir`.
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

    asyncio.create_task(_job())
