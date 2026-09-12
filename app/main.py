"""Entrypoint bot Telegram (WP-01 bootstrap only, tanpa handler terdaftar).

Per AGENTS.md §5: logging dari stdlib, token hanya dari env.
Jalur ini tidak mengimpor yt-dlp.
"""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from app.config import get_settings
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
    logger.info("application built (no handlers registered yet, WP-01)")

    # T-055: satu instance rate limiter seumur hidup aplikasi, dibagikan ke handler
    # WP-06 lewat bot_data (FR-011).
    application.bot_data["rate_limiter"] = UserRateLimiter(settings)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("polling started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
