"""Entrypoint bot Telegram (WP-01 bootstrap, WP-06 register handlers).

Per AGENTS.md §5: logging dari stdlib, token hanya dari env.
Jalur ini tidak mengimpor yt-dlp.
"""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.config import get_settings
from app.handlers.download import download_handler
from app.handlers.start import help_command, start
from app.services.rate_limiter import UserRateLimiter

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = (
        Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    )
    logger.info("application built")

    application.bot_data["rate_limiter"] = UserRateLimiter(settings)
    # T-111 (FR-010, NFR Reliability): semaphore dibangun PER-instance aplikasi
    # (bukan module-level) agar tiap event-loop punya slot-nya sendiri; handler
    # WP-11 baca lewat `bot_data.get("semaphore")`: fallback `_job` self-heal bila
    # ditambahkan di luar `main()` (test langsung). `MAX_CONCURRENT_DOWNLOADS` dari
    # env; production value = settings.max_concurrent_downloads.
    application.bot_data["semaphore"] = asyncio.Semaphore(settings.max_concurrent_downloads)
    application.bot_data["settings"] = settings

    # WP-06: handler /start, /help, deteksi URL (FR-001..FR-003, FR-011).
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("polling started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
