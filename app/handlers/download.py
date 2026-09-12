"""Handler URL detection + dispatch (FR-003..FR-005, FR-007, FR-011)."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import ContextTypes

from app.services import downloader as downloader_service
from app.services.errors import RateLimitedError, UploadError
from app.services.uploader import send_video
from app.services.validator import UnsupportedUrlError, extract_url, validate_url

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
    """T-087: setelah download sukses, kirim video ke Telegram."""
    try:
        await send_video(
            bot=context.bot,
            chat_id=chat_id,
            file_path=result.path,
            title=result.metadata.get("title") or "",
            url=url,
            max_file_size_mb=settings.max_file_size_mb,
            metadata=result.metadata,
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
        try:
            result = await downloader_service.download(url, settings)
            await _upload_after_download(context, url, result, chat_id, settings)
        except Exception:
            logger.exception("download job failed for %s", url)

    asyncio.create_task(_job())
