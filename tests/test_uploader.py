"""Test uploader WP-08 (T-081..T-086, T-087), tanpa network."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

from app.config import Settings
from app.services.downloader import DownloadResult
from app.services.errors import UploadError
from app.services.uploader import build_caption, send_video


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_video = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


def _make_file(tmp_path: Path, name: str, size: int) -> Path:
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return p


def _make_update(text: str, chat_id: int = 123456):
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


def _make_context(bot, settings):
    context = MagicMock()
    context.bot = bot
    context.bot_data = {"rate_limiter": _FakeLimiter(), "settings": settings}
    return context


class _FakeLimiter:
    async def acquire(self, chat_id):
        return None


@pytest.fixture
def settings(tmp_path):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    return Settings.model_construct(
        telegram_bot_token=" ".join(["dummy", "token"]),
        log_level="INFO",
        download_dir=str(download_dir),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
    )


# ---- build_caption (T-081) ----


def test_build_caption_instagram():
    cap = build_caption("my reel", "https://www.instagram.com/reel/xxx/")
    assert cap == "🎬 my reel\n\nSource: Instagram"


def test_build_caption_facebook():
    cap = build_caption("fb clip", "https://fb.watch/abc")
    assert cap == "🎬 fb clip\n\nSource: Facebook"


def test_build_caption_empty_title():
    cap = build_caption("", "https://www.instagram.com/reel/xxx/")
    assert cap == "🎬 \n\nSource: Instagram"


# ---- send_video: sukses < 50 MB (T-084) ----


async def test_send_video_small_success(mock_bot, tmp_path):
    f = _make_file(tmp_path, "vid.mp4", 1024)

    await send_video(
        bot=mock_bot,
        chat_id=123,
        file_path=f,
        title="my reel",
        url="https://www.instagram.com/reel/xxx/",
        max_file_size_mb=50,
    )

    mock_bot.send_video.assert_awaited_once()
    call = mock_bot.send_video.call_args
    assert call.kwargs["chat_id"] == 123
    assert call.kwargs["video"] == str(f)
    assert call.kwargs["caption"] == "🎬 my reel\n\nSource: Instagram"
    assert call.kwargs["read_timeout"] == 30
    mock_bot.send_document.assert_not_awaited()


# ---- send_video: fallback send_document saat size > limit (T-084) ----


async def test_send_video_too_large_fallback_to_document(mock_bot, tmp_path):
    # Ukp file disimulasikan via metadata (no big file on disk). Path tetap
    # ada agar test bisa assert argumen (str(file_path), caption, read_timeout).
    limit_bytes = 50 * 1024 * 1024
    fake_size_bytes = limit_bytes + 1
    f = _make_file(tmp_path, "big.mp4", 1024)
    metadata = {"filesize": fake_size_bytes}

    await send_video(
        bot=mock_bot,
        chat_id=456,
        file_path=f,
        title="big reel",
        url="https://www.instagram.com/reel/yyy/",
        max_file_size_mb=50,
        metadata=metadata,
    )

    mock_bot.send_video.assert_not_awaited()
    mock_bot.send_document.assert_awaited_once()
    call = mock_bot.send_document.call_args
    assert call.kwargs["document"] == str(f)
    assert call.kwargs["caption"] == "🎬 big reel\n\nSource: Instagram"
    assert call.kwargs["read_timeout"] == 30


# ---- send_video: TelegramError -> UploadError (T-085) ----


async def test_send_video_telegram_error_raises_upload_error(mock_bot, tmp_path):
    mock_bot.send_video = AsyncMock(side_effect=TelegramError("rate limited"))
    f = _make_file(tmp_path, "vid.mp4", 1024)

    with pytest.raises(UploadError, match="Upload ke Telegram gagal"):
        await send_video(
            bot=mock_bot,
            chat_id=789,
            file_path=f,
            title="fail reel",
            url="https://fb.watch/xyz",
            max_file_size_mb=50,
        )

    mock_bot.send_document.assert_not_awaited()


async def test_send_video_document_telegram_error_raises_upload_error(mock_bot, tmp_path):
    """Jalur fallback document juga menerjemahkan TelegramError -> UploadError."""
    mock_bot.send_document = AsyncMock(side_effect=TelegramError("file too big"))
    fake_size_bytes = 51 * 1024 * 1024
    f = _make_file(tmp_path, "big.mp4", 1024)  # ukuran nyata via metadata

    with pytest.raises(UploadError, match="Upload ke Telegram gagal"):
        await send_video(
            bot=mock_bot,
            chat_id=999,
            file_path=f,
            title="big fail",
            url="https://www.instagram.com/reel/zzz/",
            max_file_size_mb=50,
            metadata={"filesize": fake_size_bytes},
        )


# ---- T-087: integrasi handler -> send_video dengan param benar ----


async def test_handler_uploads_after_download(mock_bot, tmp_path, settings):
    from app.handlers import download as download_mod
    from app.handlers.download import download_handler

    video = tmp_path / "out.mp4"
    video.write_bytes(b"x" * 1024)

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": "judul reels"})

    update = _make_update("https://www.instagram.com/reel/xxx/")
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(download_mod.downloader_service, "download", fake_download),
    ):
        await download_handler(update, _make_context(mock_bot, settings))
        await asyncio.wait_for(jobs[0], timeout=2)

    mock_bot.send_video.assert_awaited_once()
    call = mock_bot.send_video.call_args
    assert call.kwargs["chat_id"] == 123456
    assert call.kwargs["video"] == str(video)
    assert call.kwargs["caption"] == "🎬 judul reels\n\nSource: Instagram"


# ---- T-085: UploadError di jalur handler -> pesan error terlihat user ----


async def test_handler_replies_error_message_when_upload_fails(mock_bot, tmp_path, settings):
    from app.handlers import download as download_mod
    from app.handlers.download import download_handler

    video = tmp_path / "out.mp4"
    video.write_bytes(b"x" * 1024)

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": "judul"})

    update = _make_update("https://fb.watch/abc")
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(download_mod.downloader_service, "download", fake_download),
        patch.object(
            download_mod,
            "send_video",
            AsyncMock(side_effect=UploadError("Upload ke Telegram gagal: boom")),
        ),
    ):
        await download_handler(update, _make_context(mock_bot, settings))
        await asyncio.wait_for(jobs[0], timeout=2)

    mock_bot.send_message.assert_awaited_once()
    sent = mock_bot.send_message.call_args.kwargs
    assert sent["chat_id"] == 123456
    assert sent["text"] == "⚠️ Gagal mengirim video ke Telegram."
    assert "boom" not in sent["text"]  # exception mentah tidak bocor


async def test_handler_unclassified_upload_error_logged_and_replies(
    mock_bot, tmp_path, settings, caplog
):
    """T-087 + NFR Reliability: exception tak terklasifikasi tidak membunuh job/bot."""

    from app.handlers import download as download_mod
    from app.handlers.download import download_handler

    video = tmp_path / "out.mp4"
    video.write_bytes(b"x" * 1024)

    async def fake_download(url, _settings):
        return DownloadResult(path=video, metadata={"title": "judul"})

    update = _make_update("https://www.instagram.com/reel/xxx/")
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    with caplog.at_level(logging.ERROR, logger="app.handlers.download"):
        with (
            patch.object(download_mod.asyncio, "create_task", side_effect=spy),
            patch.object(download_mod.downloader_service, "download", fake_download),
            patch.object(
                download_mod, "send_video", AsyncMock(side_effect=RuntimeError("salah total"))
            ),
        ):
            await download_handler(update, _make_context(mock_bot, settings))
            await asyncio.wait_for(jobs[0], timeout=2)

    assert jobs[0].done() and not jobs[0].cancelled()
    assert "salah total" in caplog.text  # detail masuk log, bukan ke user
    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["text"] == "⚠️ Gagal mengirim video."
    assert update.message.reply_text.await_count == 1  # hanya ack '⏳'
