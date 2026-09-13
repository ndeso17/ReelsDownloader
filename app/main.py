"""Entrypoint bot Telegram (WP-01 bootstrap, WP-06 register handlers).

Per AGENTS.md §5: logging dari stdlib, token hanya dari env.
Jalur ini tidak mengimpor yt-dlp.
"""

from __future__ import annotations

import asyncio
import inspect
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.config import get_settings
from app.handlers.account import get_id, menu, set_user
from app.handlers.download import download_handler
from app.handlers.start import help_command, start
from app.services.rate_limiter import UserRateLimiter
from app.services.user_store import load_users

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

    # T-156 (FR-012, FR-016): muat whitelist dari users_file sebelum handler diregistrasi.
    # Saat file hilang/rusak, load_users mengembalikan `{}` + logger.warning, jadi bot
    # tetap hidup (tidak pernah raise). getattr = fallback untuk Settings/model_construct
    # lama tanpa field v2.2 (test WP-06/WP-10) supaya startup tidak berubah.
    users_file = getattr(settings, "users_file", None) or "users.json"
    application.bot_data["users"] = load_users(users_file)

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

    # WP-15: handler akses v2.2: `/getID`, `/menu`, `/setUser` (FR-012, FR-014, FR-016).
    application.add_handler(CommandHandler("getID", get_id))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("setUser", set_user))

    await application.initialize()
    await application.start()
    # T-156 (FR-016): daftar command Telegram disinkronkan dengan menu v2.2
    # (set_my_commands butuh bot ter-initialize; bukan jalur request). Sinkronisasi
    # ini bukan jalur kritis: gagal (mis. token/network) hanya di-log, bot tetap
    # polling. Pola await-if-awaitable menjaga test lama yang memakai MagicMock
    # (`application.bot` auto-attr bukan AsyncMock) tetap hijau tanpa diutak-atik.
    try:
        outcome = application.bot.set_my_commands(
            [
                ("start", "Selamat datang + menu singkat"),
                ("help", "Panduan penggunaan"),
                ("getID", "Lihat Telegram ID kamu"),
                ("menu", "Daftar command + status akses"),
                ("advance", "Download dengan pilihan (user terdaftar)"),
                ("setUser", "Kelola user (admin, private mode)"),
                ("cancel", "Batalkan dialog aktif (user terdaftar)"),
                ("stats", "Statistik pemakaian (admin)"),
            ]
        )
        if inspect.isawaitable(outcome):
            await outcome
    except Exception:
        logger.warning("set_my_commands gagal, daftar command tidak disinkronkan")
    await application.updater.start_polling()
    logger.info("polling started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
