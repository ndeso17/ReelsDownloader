"""Handler URL detection + dispatch (FR-003..FR-005, FR-011, NFR Performance/Reliability)."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import ContextTypes

from app.services import downloader as downloader_service
from app.services.errors import RateLimitedError
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
            await downloader_service.download(url, settings)
        except Exception:
            logger.exception("download job failed for %s", url)

    asyncio.create_task(_job())
