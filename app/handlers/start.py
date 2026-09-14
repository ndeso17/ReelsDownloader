"""Handler /start dan /help (FR-001, FR-002) + catatan user baru (FR-015, FR-021).

Tetap TIDAK ada gate akses di sini (PRD §4): `/start` publik. Yang bertambah di
WP-16 hanya pencatatan stats + notifikasi admin fire-and-forget, jadi welcome
tetap dibalas < 2 dtk tanpa menunggu jaringan (NFR Performance).
"""

from __future__ import annotations

import asyncio
import logging

from app.services.stats import build_new_user_message, notify_new_user

logger = logging.getLogger(__name__)

_WELCOME_TEXT = (
    "👋 Instagram/Facebook/TikTok Downloader\n"
    "\n"
    "Kirim link Instagram, Facebook, atau TikTok Reels\n"
    "dan saya akan mencoba mengunduh videonya.\n"
    "\n"
    "Contoh:\n"
    "https://www.instagram.com/reel/xxxxx/\n"
    "https://www.tiktok.com/@user/video/1234567890"
)

#: T-155 (FR-016): blok menu ringkas yang digabung ke /start, dikirim terpisah
#: supaya teks welcome lama tetap muncul utuh (test WP-06 mengunci teks itu).
_MENU_SHORT_TEXT = (
    "📋 Command singkat:\n"
    "/getID  , lihat Telegram ID kamu (publik)\n"
    "/menu   , daftar command + status akses (publik)\n"
    "/setUser, kelola user (admin, private mode)\n"
    "/advance, download dengan dialog pilihan (user terdaftar)\n"
    "/cancel , batalkan dialog aktif (user terdaftar)\n"
    "/stats  , statistik pemakaian (admin)"
)


async def _notify_and_persist(bot, settings, stats, stats_file: str, text: str) -> None:
    """Satu task latar: kirim notifikasi admin, lalu flush `stats.json`.

    `notify_new_user` sudah menelan semua exception (kontrak FR-021) sehingga
    notifikasi gagal tidak menghentikan persistensi. `stats.save` juga tidak
    pernah raise (pola `user_store.save_users`); try/except di sini hanya
    penjaga terakhir agar task fire-and-forget tidak meninggalkan "Task
    exception was never retrieved" di log.
    """
    await notify_new_user(bot, settings, text)
    try:
        await asyncio.to_thread(stats.save, stats_file)
    except Exception as exc:  # pragma: no cover - jalur darurat, save tidak raise
        logger.warning("persist stats gagal: %s", exc)


async def start(update, context):
    # T-155: teks welcome lama harus tetap jadi argumen pertama `reply_text`
    # (test WP-06 `call_args.args[0]`); tidak ada kata yang berubah di bawah.
    await update.effective_message.reply_text(_WELCOME_TEXT)

    # T-163 (FR-015, FR-021, SC 17): catat user unik. `bot_data.get("stats")` boleh
    # None (jalur test lama WP-06/08/09/10 yang membuat bot_data manual) atau
    # `effective_user` boleh None (update tanpa pengirim): dua-duanya berarti
    # "skip pencatatan", bukan error.
    stats = context.bot_data.get("stats")
    user = update.effective_user
    if stats is not None and user is not None:
        settings = context.bot_data.get("settings")
        if stats.record_user(
            user.id,
            first_name=getattr(user, "first_name", "") or "",
            username=getattr(user, "username", "") or "",
        ):
            # Notifikasi dijadwalkan DI SINI, di modul `start` (bukan `download.py`):
            # spy test lama mem-patch `download_mod.asyncio.create_task`, jadi tidak
            # boleh ada create_task baru di modul itu di luar WP-17. Fire-and-forget:
            # `/start` tidak await pengiriman (NFR Performance), dan flush atomik
            # stats hanya terjadi pada perubahan bermakna (user baru) + post_shutdown
            # (mitigasi risiko hot-path, lihat Log WP-16).
            text = build_new_user_message(user, stats.total_users)
            stats_file = getattr(settings, "stats_file", None) or "stats.json"
            asyncio.create_task(
                _notify_and_persist(context.bot, settings, stats, stats_file, text),
                name="stats-notify-flush",
            )

    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=_MENU_SHORT_TEXT)


async def help_command(update, context):
    await update.effective_message.reply_text(
        "Cara penggunaan:\n"
        "• /start, info bot dan welcome\n"
        "• /help, panduan ini\n"
        "• /getID, lihat Telegram ID kamu (publik)\n"
        "• /menu, daftar command + status akses (publik)\n"
        "• Kirim URL Instagram, Facebook, atau TikTok Reels untuk mengunduh video\n"
        "\n"
        "Contoh URL:\n"
        "https://www.instagram.com/reel/xxxxx/\n"
        "https://www.tiktok.com/@user/video/1234567890"
    )
