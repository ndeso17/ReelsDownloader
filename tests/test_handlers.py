"""Test handler WP-06 (T-065..T-067, FR-001..FR-003, FR-011), tanpa network.

Semua update/context/bot adalah MagicMock/AsyncMock; tidak ada panggilan
Telegram dan `downloader.download` selalu di-patch (AGENTS.md §4.6).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.handlers.download import download_handler
from app.handlers.start import help_command, start
from app.services import downloader as downloader_service
from app.services.downloader import DownloadResult
from app.services.errors import DownloadFailedError
from app.services.rate_limiter import UserRateLimiter
from tests.queue_support import JobCollector

VALID_URL = "https://www.instagram.com/reel/xxxxx/"
START_MARKER = "👋 Instagram/Facebook/YouTube Downloader"


def make_update(text: str, chat_id: int = 123456) -> MagicMock:
    """Update tiruan: message.text + reply_text AsyncMock (tanpa network)."""
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


def make_context(rate_limiter: UserRateLimiter, settings: Settings) -> MagicMock:
    context = MagicMock()
    context.bot_data = {"rate_limiter": rate_limiter, "settings": settings}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


@pytest.fixture
def settings(tmp_path) -> Settings:
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial; hindari literal token
    return Settings.model_construct(
        telegram_bot_token=dummy_token,
        log_level="INFO",
        download_dir=str(download_dir),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
    )


@pytest.fixture
def rl() -> UserRateLimiter:
    """Limiter dengan jam frozen 0.0, deterministik, tanpa freezegun (T-054 rule)."""
    limiter = UserRateLimiter(10)
    limiter.time_source = lambda: 0.0
    return limiter


def reply_texts(update: MagicMock) -> list[str]:
    return [c.args[0] for c in update.message.reply_text.call_args_list]


# ---------------- T-062 /start (FR-001): teks persis PRD ----------------


async def test_start_text_matches_prd_fr001():
    update = make_update("/start")
    await start(update, make_context(UserRateLimiter(10), Settings.model_construct()))
    assert update.message.reply_text.call_args.args[0] == (
        "👋 Instagram/Facebook/YouTube Downloader\n"
        "\n"
        "Kirim link Instagram, Facebook, atau YouTube Reels/Short\n"
        "dan saya akan mencoba mengunduh videonya.\n"
        "\n"
        "Contoh:\n"
        "https://www.instagram.com/reel/xxxxx/\n"
        "https://www.youtube.com/watch?v=xxxxx\n"
    )


# ---------------- T-062 /help (FR-002) ----------------


async def test_help_contains_usage_instructions():
    update = make_update("/help")
    await help_command(update, MagicMock())
    lowered = update.message.reply_text.call_args.args[0].lower()
    assert "cara penggunaan" in lowered
    assert "kirim" in lowered
    assert "instagram" in lowered and "facebook" in lowered
    assert "youtube" in lowered


# ---------------- T-063 teks tanpa URL → minta URL, tanpa crash ----------------


async def test_no_url_replies_instruction_without_crash(rl, settings):
    update = make_update("halo, apa kabar?")
    await download_handler(update, make_context(rl, settings))
    assert START_MARKER in reply_texts(update)[0]
    assert rl.last_map == {}  # acquire tidak tersentuh


# ---------------- T-063/T-066 URL non-IG/FB ditolak (FR-004) ----------------


async def test_unsupported_url_replies_error(rl, settings):
    update = make_update("cek https://open.spotify.com/track/123 ya")
    await download_handler(update, make_context(rl, settings))
    texts = reply_texts(update)
    assert len(texts) == 1
    assert "Host tidak didukung" in texts[0]
    assert rl.last_map == {}  # validasi gagal sebelum rate limiter


# ---------------- T-067 rate limit → reply retry-after (FR-011) ----------------


async def test_rate_limited_replies_retry_after(rl, settings):
    collector = JobCollector(worker_count=1)
    first = make_update(VALID_URL)
    with collector.install():
        await download_handler(first, make_context(rl, settings))
    assert collector.scheduled >= 1, "request pertama masuk antrean"
    collector.close_pending()  # jangan jalankan job di test ini

    blocked = make_update(VALID_URL)
    with collector.install():
        await download_handler(blocked, make_context(rl, settings))

    texts = reply_texts(blocked)
    assert len(texts) == 1
    assert "Terlalu sering" in texts[0]
    assert "coba lagi dalam" in texts[0] and "detik" in texts[0]
    assert "10.0" in texts[0]  # retry_after dari jam frozen
    assert collector.scheduled == 0, "job tidak dijadwalkan saat rate-limited"


# ---------------- T-063 URL valid → ack '⏳' + create_task ----------------


async def test_valid_url_acks_and_spawns_task(rl, settings):
    collector = JobCollector(worker_count=1)
    update = make_update(f"tolong unduh {VALID_URL} dong")
    with (
        collector.install(),
        patch.object(downloader_service, "download", AsyncMock()),
    ):
        await download_handler(update, make_context(rl, settings))
        await collector.drain()

    assert "⏳ Sedang memproses..." in reply_texts(update)
    assert collector.scheduled >= 1, "pekerjaan dijadwalkan"
    assert set(rl.last_map) == {123456}  # acquire lolos sebelum ack


# ---------------- NFR Performance: handler return sebelum download selesai ----------------


async def test_handler_returns_before_download_finishes(rl, settings):
    gate = asyncio.Event()

    async def slow_download(url, _settings):
        await gate.wait()
        return DownloadResult(path=Path(_settings.download_dir) / "x.mp4", metadata={})

    collector = JobCollector(worker_count=1)
    update = make_update(VALID_URL)

    with (
        collector.install(),
        patch.object(downloader_service, "download", slow_download),
    ):
        start = time.monotonic()
        await download_handler(update, make_context(rl, settings))  # harus langsung return
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"handler > 2dtk ({elapsed:.3f})"
        assert collector.scheduled == 1, "pekerjaan dijadwalkan"
        assert not collector.done, "download belum mulai saat handler balik"
        gate.set()
        await collector.drain()


# ---------------- NFR Reliability: task gagal → di-log, loop tidak crash ----------------


async def test_failed_download_job_is_logged_not_raised(rl, settings, caplog):
    async def boom(url, _settings):
        raise DownloadFailedError("simulasi yt-dlp mati")

    collector = JobCollector(worker_count=1)
    update = make_update(VALID_URL)

    with caplog.at_level(logging.ERROR, logger="app.handlers.download"):
        with collector.install(), patch.object(downloader_service, "download", boom):
            await download_handler(update, make_context(rl, settings))
            await asyncio.wait_for(collector.drain(), timeout=2)

    assert collector.done, "job selesai dieksekusi"
    assert "simulasi yt-dlp mati" in caplog.text  # traceback/penyebab masuk log
