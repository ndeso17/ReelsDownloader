"""Test WP-10 (T-102, FR-009): user_message() + integrasi handler T-103/T-104.

Pesan wajib ramah pengguna: tanpa traceback, tanpa isi exception mentah.
Handler diuji dengan mock update/context/bot (pola WP-06/WP-09), tanpa
jaringan nyata (AGENTS.md §4.6).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.handlers import download as download_mod
from app.handlers.download import download_handler
from app.services import downloader as downloader_service
from app.services.downloader import DownloadResult
from app.services.errors import (
    DownloadFailedError,
    FFmpegFailedError,
    FileTooLargeError,
    NetworkError,
    PrivateVideoError,
    RateLimitedError,
    UploadError,
    VideoNotFoundError,
    user_message,
)
from app.services.validator import UnsupportedUrlError
from tests.queue_support import JobCollector

#: Isi exception mentah yang dipakai pemantik di bawah: tidak boleh bocor.
RAW = "Detail mentah: /home/app/secret.mp4 Traceback most recent call last"

MESSAGES = [
    pytest.param(UnsupportedUrlError(RAW), "❌ URL tidak didukung. Kirim link Instagram/Facebook."),
    pytest.param(ValueError(RAW), "❌ URL tidak valid"),
    pytest.param(PrivateVideoError(RAW), "🔒 Video private/terbatas."),
    pytest.param(VideoNotFoundError(RAW), "🔍 Video tidak ditemukan."),
    pytest.param(DownloadFailedError(RAW), "⚠️ Gagal mengunduh."),
    pytest.param(FFmpegFailedError(RAW), "⚠️ Gagal memproses video."),
    pytest.param(FileTooLargeError(RAW), "📏 File terlalu besar."),
    pytest.param(UploadError(RAW), "⚠️ Gagal mengirim ke Telegram."),
    pytest.param(TimeoutError(RAW), "⏱️ Timeout."),
    pytest.param(RateLimitedError(7.4), "⏳ Terlalu sering; coba lagi dalam 7 detik"),
    pytest.param(NetworkError(RAW), "⚠️ Gagal terhubung ke internet. Coba lagi."),
    pytest.param(RuntimeError(RAW), "⚠️ Terjadi kesalahan. Coba lagi sebentar lagi."),
]


@pytest.mark.parametrize(("exc", "expected"), MESSAGES)
def test_user_message_maps_every_condition_one_to_one(exc: Exception, expected: str) -> None:
    """T-101/T-102 (FR-009): SATU-PERSATU 9 kondisi PRD §9 + jaring generic."""
    assert user_message(exc) == expected


@pytest.mark.parametrize(("exc", "_expected"), MESSAGES)
def test_user_message_never_leaks_raw_exception_text(exc: Exception, _expected: str) -> None:
    """T-102 (FR-009): pesan non-kosong, tanpa traceback/isi exception mentah."""
    msg = user_message(exc)
    assert msg
    assert "Traceback" not in msg and "\n  File" not in msg
    assert RAW not in msg
    assert type(exc).__name__ not in msg


def test_user_message_maps_unknown_exception_to_generic() -> None:
    """Exception tak dikenal (mis. bug internal) tetap dapat pesan bersih."""
    msg = user_message(KeyError(RAW))
    assert "Traceback" not in msg and "\n  File" not in msg
    assert RAW not in msg


# ---------------- T-103: jalur _job: pesan user_message sampai ke chat ----------------

VALID_URL = "https://www.instagram.com/reel/xxxxx/"


def _make_update(text: str, chat_id: int = 123456) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


def _make_context(bot, settings) -> MagicMock:
    context = MagicMock()
    context.bot = bot
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    context.bot_data = {"rate_limiter": limiter, "settings": settings}
    return context


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_video = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def settings(tmp_path) -> Settings:
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    return Settings.model_construct(
        telegram_bot_token=" ".join(["dummy", "token"]),
        log_level="INFO",
        download_dir=str(download_dir),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
    )


async def _run_failing_job(bot, settings, exc: Exception):
    """Jalankan handler dengan download yang melempar *exc*; kembalikan collector."""
    update = _make_update(VALID_URL)

    async def boom(url, _settings):
        raise exc

    collector = JobCollector(worker_count=1)
    with collector.install(), patch.object(downloader_service, "download", boom):
        await download_handler(update, _make_context(bot, settings))
        await collector.drain()
    return collector, update


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        pytest.param(PrivateVideoError(RAW), "🔒 Video private/terbatas."),
        pytest.param(VideoNotFoundError(RAW), "🔍 Video tidak ditemukan."),
        pytest.param(FileTooLargeError(RAW), "📏 File terlalu besar."),
        pytest.param(FFmpegFailedError(RAW), "⚠️ Gagal memproses video."),
        pytest.param(TimeoutError(RAW), "⏱️ Timeout."),
        pytest.param(DownloadFailedError(RAW), "⚠️ Gagal mengunduh."),
        pytest.param(RuntimeError(RAW), "⚠️ Terjadi kesalahan. Coba lagi sebentar lagi."),
    ],
)
async def test_job_failure_replies_clean_user_message(mock_bot, settings, exc, expected):
    """T-103 (FR-009 + NFR Reliability): job gagal -> pesan bersih, task tetap hidup."""
    collector, update = await _run_failing_job(mock_bot, settings, exc)
    assert collector.done, "job selesai dieksekusi"
    mock_bot.send_message.assert_awaited_once()
    sent = mock_bot.send_message.call_args.kwargs
    assert sent["chat_id"] == 123456
    assert sent["text"] == expected
    assert RAW not in sent["text"]
    # hanya ack '⏳' yang masuk reply_text; pesan error via bot.send_message
    assert update.message.reply_text.await_args_list[-1].args[0] == "⏳ Sedang memproses..."


# ---------------- T-104: metadata/caption disanitasi sebelum kirim ----------------


async def test_metadata_sanitized_before_send_video(mock_bot, settings):
    """T-104 (NFR Security): title control-char/panjang disanitasi sebelum upload."""
    dl_dir = Path(settings.download_dir)
    video = dl_dir / "abc.mp4"
    video.write_bytes(b"x" * 16)
    dirty_title = "\x00" + "j" * 150 + "\x7f"

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": dirty_title, "uploader": "\x01x"})

    collector = JobCollector(worker_count=1)
    update = _make_update(VALID_URL)
    upload = AsyncMock()
    with (
        collector.install(),
        patch.object(downloader_service, "download", fake_download),
        patch.object(download_mod, "send_video", upload),
    ):
        await download_handler(update, _make_context(mock_bot, settings))
        await collector.drain()

    kwargs = upload.await_args.kwargs
    assert kwargs["metadata"]["uploader"] == "x"
    assert kwargs["title"] == "j" * 100  # truncate + strip control char
    assert "\x00" not in kwargs["title"] and "\x7f" not in kwargs["title"]
