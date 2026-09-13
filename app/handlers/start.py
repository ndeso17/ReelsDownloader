"""Handler /start (FR-001)."""

from __future__ import annotations


async def start(update, context):
    await update.effective_message.reply_text(
        "👋 Instagram/Facebook Downloader\n"
        "\n"
        "Kirim link Instagram atau Facebook Reels\n"
        "dan saya akan mencoba mengunduh videonya.\n"
        "\n"
        "Contoh:\n"
        "https://www.instagram.com/reel/xxxxx/"
    )


async def help_command(update, context):
    await update.effective_message.reply_text(
        "Cara penggunaan:\n"
        "• /start, info bot\n"
        "• /help, panduan ini\n"
        "• Kirim URL Instagram atau Facebook Reels\n"
        "  untuk mengunduh video.\n"
        "\n"
        "Contoh URL:\n"
        "https://www.instagram.com/reel/xxxxx/"
    )
