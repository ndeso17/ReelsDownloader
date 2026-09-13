"""Handler /start dan /help (FR-001, FR-002). Tidak ada gate akses (PRD §4)."""

from __future__ import annotations

_WELCOME_TEXT = (
    "👋 Instagram/Facebook Downloader\n"
    "\n"
    "Kirim link Instagram atau Facebook Reels\n"
    "dan saya akan mencoba mengunduh videonya.\n"
    "\n"
    "Contoh:\n"
    "https://www.instagram.com/reel/xxxxx/"
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


async def start(update, context):
    await update.effective_message.reply_text(_WELCOME_TEXT)
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=_MENU_SHORT_TEXT)


async def help_command(update, context):
    await update.effective_message.reply_text(
        "Cara penggunaan:\n"
        "• /start, info bot dan welcome\n"
        "• /help, panduan ini\n"
        "• /getID, lihat Telegram ID kamu (publik)\n"
        "• /menu, daftar command + status akses (publik)\n"
        "• Kirim URL Instagram atau Facebook Reels untuk mengunduh video\n"
        "\n"
        "Contoh URL:\n"
        "https://www.instagram.com/reel/xxxxx/"
    )
