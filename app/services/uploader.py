"""Telegram uploader (FR-007, FR-009 upload-failure branch).

WP-08: kirim video hasil unduhan ke chat pengguna lewat ``bot.send_video``;
bila ukuran file melebihi ``MAX_FILE_SIZE_MB`` jatuh ke ``bot.send_document``.
Ukuran diperiksa di sini (metadata ``filesize`` -> fallback stat disk), bukan
di downloader. ``timeout=30`` (T-082) diteruskan sebagai ``read_timeout``
python-telegram-bot 22.8 tidak punya parameter ``timeout`` di
``send_video``/``send_document`` (lihat Log WP-08 + FINDINGS). Tidak ada
network nyata di test: semua bot method di-AsyncMock (AGENTS.md §4.6).
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram.error import TelegramError

from app.services.errors import UploadError
from app.services.validator import detect_platform

logger = logging.getLogger(__name__)

#: T-082: timeout API Telegram untuk upload (detik).
UPLOAD_TIMEOUT_SECONDS = 30


#: FR-007/FR-020: nama tampilan platform di caption. Peta eksplisit, bukan
#: `.capitalize()` (itu menghasilkan "Tiktok" yang salah kapitalisasi).
_PLATFORM_DISPLAY = {"instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok"}


def build_caption(
    title: str,
    url: str,
    *,
    audio: bool = False,
    note: str | None = None,
) -> str:
    """Caption FR-007: ``🎬 {title}\\n\\nSource: Instagram|Facebook|TikTok``.

    ``{platform}`` dari ``detect_platform()`` (T-038/T-182) dipetakan lewat
    ``_PLATFORM_DISPLAY``; title kosong tetap menghasilkan caption valid (bukan
    string kosong). ``audio=True`` => emoji ``🎵`` (FR-018); ``note`` (mis.
    ``(720p→480p)``) ditempel di baris Source hanya saat hasil ≠ permintaan
    (FR-017) - default ``audio=False, note=None`` byte-identik WP-08.
    """
    platform = _PLATFORM_DISPLAY[detect_platform(url)]
    emoji = "🎵" if audio else "🎬"
    caption = f"{emoji} {title}\n\nSource: {platform}"
    if note:
        caption = f"{caption} {note}"
    return caption


def _file_size_bytes(file_path: Path, metadata: dict | None) -> int:
    """Ukuran file: metadata ``filesize`` bila ada, kalau tidak sitat disk."""
    size = (metadata or {}).get("filesize")
    if isinstance(size, int) and size > 0:
        return size
    return file_path.stat().st_size


async def send_video(
    bot,
    chat_id: int,
    file_path: Path,
    title: str,
    url: str,
    *,
    max_file_size_mb: int,
    metadata: dict | None = None,
    note: str | None = None,
) -> None:
    """Upload satu video ke Telegram (FR-007) dengan fallback document.

    `note` (WP-19, FR-017) ditempel di baris Source hanya saat kualitas hasil
    ≠ permintaan; `note=None` caption byte-identik WP-08.
    Naik: ``UploadError`` (``TelegramError`` dari API), ``UnsupportedUrlError``
    (URL tak dikenal, sudah harus lolos validasi WP-03 sebelum sampai sini).
    """
    caption = build_caption(title, url, note=note)
    size_bytes = _file_size_bytes(file_path, metadata)
    limit_bytes = max_file_size_mb * 1024 * 1024
    send_document = size_bytes > limit_bytes

    try:
        if send_document:
            await bot.send_document(
                chat_id=chat_id,
                document=str(file_path),
                caption=caption,
                read_timeout=UPLOAD_TIMEOUT_SECONDS,
            )
            logger.info("upload via send_document: %s (%d bytes)", file_path, size_bytes)
        else:
            await bot.send_video(
                chat_id=chat_id,
                video=str(file_path),
                caption=caption,
                read_timeout=UPLOAD_TIMEOUT_SECONDS,
            )
            logger.info("upload via send_video: %s (%d bytes)", file_path, size_bytes)
    except TelegramError as exc:
        logger.warning("Telegram upload failed for chat %s: %s", chat_id, exc)
        raise UploadError(f"Upload ke Telegram gagal: {exc}") from exc


async def send_audio(
    bot,
    chat_id: int,
    file_path: Path,
    title: str,
    url: str,
    *,
    max_file_size_mb: int,
) -> None:
    """Upload satu file `.mp3` (FR-018): `send_audio`, fallback document.

    Ukuran dari `stat` nyata file hasil ekstraksi (metadata pra-unduh bukan
    ukuran mp3). Caption `🎵 {title}` + baris Source (FR-018/FR-007).
    Naik: ``UploadError``.
    """
    caption = build_caption(title, url, audio=True)
    size_bytes = _file_size_bytes(file_path, None)
    limit_bytes = max_file_size_mb * 1024 * 1024

    try:
        if size_bytes > limit_bytes:
            await bot.send_document(
                chat_id=chat_id,
                document=str(file_path),
                caption=caption,
                read_timeout=UPLOAD_TIMEOUT_SECONDS,
            )
            logger.info("upload via send_document: %s (%d bytes)", file_path, size_bytes)
        else:
            await bot.send_audio(
                chat_id=chat_id,
                audio=str(file_path),
                caption=caption,
                read_timeout=UPLOAD_TIMEOUT_SECONDS,
            )
            logger.info("upload via send_audio: %s (%d bytes)", file_path, size_bytes)
    except TelegramError as exc:
        logger.warning("Telegram audio upload failed for chat %s: %s", chat_id, exc)
        raise UploadError(f"Upload ke Telegram gagal: {exc}") from exc
