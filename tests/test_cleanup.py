"""Integrasi WP-09 (T-091/T-092/T-093, FR-008, SC §8 butir 5): cleanup file sementara.

Handler `download.py` wajib menghapus file di `download_dir` SETELAH upload
sukses MAUPUN gagal (blok `finally`, AGENTS.md §5 garis merah terakhir).
`clean_dir` asli dibiarkan jalan; assert langsung `list(dl_dir.iterdir()) == []`
pada KEDUA jalur (PLAN T-093). Hanya `downloader_service.download` +
`send_video` yang di-mock, tidak ada network (AGENTS.md §4.6).

Deviasi dari teks PLAN (dicatat di Log WP-09): T-093 menyebut `upload_video`
nama nyata di kode = `send_video` (WP-08); `get_settings().download_dir_path()`
tidak ada di `app/config.py`, dipakai `Path(settings.download_dir)` dari
fixture `settings` (tmp_path), sama seperti pola WP-06/WP-08.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.handlers import download as download_mod
from app.handlers.download import download_handler
from app.services.downloader import DownloadResult
from app.services.errors import UploadError


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
    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial; hindari literal token
    return Settings.model_construct(
        telegram_bot_token=dummy_token,
        log_level="INFO",
        download_dir=str(download_dir),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_seconds=10,
    )


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


class _FakeLimiter:
    async def acquire(self, chat_id):
        return None


def _make_context(bot, settings) -> MagicMock:
    context = MagicMock()
    context.bot = bot
    context.bot_data = {"rate_limiter": _FakeLimiter(), "settings": settings}
    return context


def _seed_video(download_dir: Path) -> Path:
    """File sementara di download_dir, meniru hasil kerja yt-dlp."""
    video = download_dir / "abc123.mp4"
    video.write_bytes(b"x" * 1024)
    return video


def _assert_dir_empty(download_dir: Path) -> None:
    """Assert FR-008/SC §8 butir 5: tidak ada file tersisa.

    Helper sinkron, assertion I/O tidak di inline coroutine (ruff ASYNC240;
    jalur produksi sudah memakai asyncio.to_thread, lihat AGENTS.md §4.4).
    """
    assert list(download_dir.iterdir()) == []


@contextlib.contextmanager
def _patched_job(download_fn, upload_mock, tasks: list[asyncio.Task]):
    """Patch create_task (rekam task background) + download + send_video."""
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        tasks.append(task)
        return task

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(download_mod.downloader_service, "download", download_fn),
        patch.object(download_mod, "send_video", upload_mock),
    ):
        yield


async def test_cleanup_after_successful_upload(mock_bot, settings):
    """T-093 jalur sukses: upload selesai -> download_dir kosong (FR-008)."""
    dl_dir = Path(settings.download_dir)
    video = _seed_video(dl_dir)

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": "judul"})

    update = _make_update("https://www.instagram.com/reel/abc/")
    context = _make_context(mock_bot, settings)
    tasks: list[asyncio.Task] = []
    with _patched_job(fake_download, AsyncMock(), tasks):
        await download_handler(update, context)
        await asyncio.wait_for(tasks[0], timeout=2)

    assert tasks[0].done() and not tasks[0].cancelled()
    _assert_dir_empty(dl_dir)
    assert not video.exists()
    mock_bot.send_message.assert_not_awaited()  # tidak ada pesan gagal


async def test_cleanup_after_failed_upload(mock_bot, settings):
    """T-093 jalur gagal upload: UploadError -> tetap cleanup + pesan generic."""
    dl_dir = Path(settings.download_dir)
    video = _seed_video(dl_dir)

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": "judul"})

    update = _make_update("https://fb.watch/xyz/")
    context = _make_context(mock_bot, settings)
    tasks: list[asyncio.Task] = []
    upload_mock = AsyncMock(side_effect=UploadError("boom"))
    with _patched_job(fake_download, upload_mock, tasks):
        await download_handler(update, context)
        await asyncio.wait_for(tasks[0], timeout=2)

    assert tasks[0].done() and not tasks[0].cancelled()
    _assert_dir_empty(dl_dir)
    mock_bot.send_message.assert_awaited_once()
    sent = mock_bot.send_message.call_args.kwargs
    assert sent["text"] == "⚠️ Gagal mengirim video ke Telegram."
    assert "boom" not in sent["text"]  # exception mentah tidak bocor ke user


async def test_cleanup_after_download_failure(mock_bot, settings):
    """T-092: exception saat download (sisa file parsial) -> finally tetap bersih."""
    dl_dir = Path(settings.download_dir)
    partial = _seed_video(dl_dir)

    async def failing_download(url, _settings):
        raise UploadError("partial file tertinggal")

    update = _make_update("https://www.instagram.com/reel/abc/")
    context = _make_context(mock_bot, settings)
    tasks: list[asyncio.Task] = []
    with _patched_job(failing_download, AsyncMock(), tasks):
        await download_handler(update, context)
        await asyncio.wait_for(tasks[0], timeout=2)

    # task tidak boleh mati (NFR Reliability: 1 URL gagal -> bot hidup)
    assert tasks[0].done() and not tasks[0].cancelled()
    _assert_dir_empty(dl_dir)
    assert not partial.exists()


async def test_cleanup_failure_logged_not_fatal(mock_bot, settings, caplog):
    """`clean_dir` raise OSError -> hanya warning log, task tetap selesai (FR-008 best-effort).

    `clean_dir` dipanggil via `asyncio.to_thread` (AGENTS.md §4.4) sehingga
    mock-nya harus sinkron: `MagicMock(side_effect=...)`, bukan AsyncMock.
    """
    dl_dir = Path(settings.download_dir)
    _seed_video(dl_dir)

    async def fake_download(url, _settings):
        return DownloadResult(path=dl_dir / "abc123.mp4", metadata={"title": "judul"})

    update = _make_update("https://www.instagram.com/reel/abc/")
    context = _make_context(mock_bot, settings)
    tasks: list[asyncio.Task] = []
    boom = MagicMock(side_effect=PermissionError("permission denied"))
    caplog.set_level(logging.WARNING, logger="app.handlers.download")
    with (
        _patched_job(fake_download, AsyncMock(), tasks),
        patch.object(download_mod, "clean_dir", boom),
    ):
        await download_handler(update, context)
        await asyncio.wait_for(tasks[0], timeout=2)

    assert tasks[0].done() and not tasks[0].cancelled()
    assert "cleanup" in caplog.text
    # baris sumber pesan (§5: traceback lengkap hanya ke log)
    assert any("cleanup" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
