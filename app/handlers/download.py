"""Handler URL detection + dispatch (FR-003..FR-005, FR-007, FR-009, FR-011)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram.ext import ContextTypes

from app.services import downloader as downloader_service
from app.services.errors import RateLimitedError, UploadError, user_message
from app.services.uploader import send_video
from app.services.validator import UnsupportedUrlError, extract_url, validate_url
from app.utils.files import clean_dir, sanitize_filename, sanitize_metadata

logger = logging.getLogger(__name__)

#: FR-001 — minta URL ketika pengguna mengirim teks tanpa URL yang valid.
_START_TEXT = (
    "👋 Instagram/Facebook Downloader\n"
    "\n"
    "Kirim link Instagram atau Facebook Reels\n"
    "dan saya akan mencoba mengunduh videonya.\n"
    "\n"
    "Contoh:\n"
    "https://www.instagram.com/reel/xxxxx/"
)


async def _upload_after_download(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    result: downloader_service.DownloadResult,
    chat_id: int,
    settings,
) -> None:
    """T-087: setelah download sukses, kirim video ke Telegram.

    T-104 (NFR Security): metadata + title dibersihkan lewat `sanitize_metadata`
    / `sanitize_filename` (WP-07) SEBELUM dikirim, jadi control char atau judul
    super panjang dari situs pihak ketiga tidak pernah masuk caption Telegram.
    String pesan upload di bawah sudah dikunci test WP-06/WP-08/WP-09
    (`tests/test_cleanup.py::test_cleanup_after_failed_upload`,
    `tests/test_uploader.py::test_handler_replies_error_message_when_upload_fails`)
    — tetap identik maknanya dengan `MSG_UPLOAD_FAILED` dari T-101.
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
    except Exception:
        logger.exception("upload job error: %s", url)
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Gagal mengirim video.")


async def download_handler(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = extract_url(update.message.text)
    if url is None:
        await update.message.reply_text(_START_TEXT)
        return

    try:
        url = validate_url(url)
    except UnsupportedUrlError as exc:
        await update.message.reply_text(str(exc))
        return

    bot_data = context.bot_data
    rate_limiter = bot_data["rate_limiter"]
    chat_id = update.effective_chat.id

    try:
        await rate_limiter.acquire(chat_id)
    except RateLimitedError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text("⏳ Sedang memproses...")

    settings = bot_data["settings"]

    async def _job():
        dl_dir = Path(settings.download_dir)
        try:
            result = await downloader_service.download(url, settings)
            await _upload_after_download(context, url, result, chat_id, settings)
        except Exception as exc:
            # T-103 (FR-009): log lengkap (traceback hanya ke log — AGENTS.md §5),
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
