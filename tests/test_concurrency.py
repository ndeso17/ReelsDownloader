"""Tests WP-11 — concurrency semaphore + ack < 2 dtk + reliability (T-114..T-116).

Synchronisasi pakai `asyncio.Event` (BUKAN `sleep`) supaya deterministik —
sesuai risiko "timing test flaky" di PLAN WP-11. Semua bot method AsyncMock;
`downloader.download` selalu di-patch (AGENTS.md §4.6, tanpa network).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.handlers import download as download_mod
from app.handlers.download import download_handler
from app.services import downloader as downloader_service
from app.services.downloader import DownloadResult
from app.services.errors import DownloadFailedError
from app.services.rate_limiter import UserRateLimiter

VALID_URL = "https://www.instagram.com/reel/xxxxx/"
ACK_TEXT = "⏳ Sedang memproses..."


# ---------------------------------------------------------------- fixtures --


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial nyata
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
    limiter = UserRateLimiter(10)
    limiter.time_source = lambda: 0.0
    return limiter


def make_update(text: str = VALID_URL, chat_id: int = 123456) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


def make_context(
    rl: UserRateLimiter,
    settings: Settings,
    semaphore: asyncio.Semaphore | None = None,
) -> MagicMock:
    bot_data: dict = {"rate_limiter": rl, "settings": settings}
    if semaphore is not None:
        bot_data["semaphore"] = semaphore
    context = MagicMock()
    context.bot_data = bot_data
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_video = AsyncMock()
    context.bot.send_document = AsyncMock()
    return context


#: batas aman tunggu job selesai (test tidak pernah sleep selama ini)
DRAIN_SECONDS = 5.0


def reply_texts(update: MagicMock) -> list[str]:
    return [c.args[0] for c in update.message.reply_text.call_args_list]


def fake_result(settings: Settings) -> DownloadResult:
    """`DownloadResult` dengan file sungguhan di disk (dipakai uploader mock)."""
    path = Path(settings.download_dir) / "oke.mp4"
    path.write_bytes(b"0123456789")
    return DownloadResult(path=path, metadata={"title": "judul"})


class JobCollector:
    """Merekam coroutine `_job()` yang di-spawn handler (`create_task` spy).

    Handler WP-06/11 memanggil `asyncio.create_task(_job())`; test perlu
    pegangan ke Task-nya untuk menunggu selesai tanpa `sleep`.
    """

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []
        self._real = asyncio.create_task

    def __call__(self, coro):
        task = self._real(coro)
        self.tasks.append(task)
        return task

    def install(self):
        return patch.object(download_mod.asyncio, "create_task", side_effect=self)

    async def drain(self) -> None:
        """Tunggu semua job yang direkam — `asyncio.timeout` (ruff ASYNC109)."""
        async with asyncio.timeout(DRAIN_SECONDS):
            await asyncio.gather(*self.tasks)


def gated_download(
    settings: Settings,
    entered: list[asyncio.Event],
    release: list[asyncio.Event],
) -> AsyncMock:
    """Mock `download()` yang menunggu izin per-job — bukti titik masuk slot."""

    async def _dl(url: str, _settings: Settings) -> DownloadResult:
        slot = len([e for e in entered if e.is_set()])
        entered[slot].set()
        await release[slot].wait()
        return fake_result(settings)

    return AsyncMock(side_effect=_dl)


# ----------------------------------------------------------------- T-114 --


async def test_three_requests_run_two_concurrently_third_waits(settings, rl):
    """T-114 (FR-010): 3 request beruntun -> maksimal 2 download serentak, ke-3 antri.

    Tiga chat berbeda (rate limiter tidak menghalangi), satu `Semaphore(2)`
    bersama. Event per-slot menandai MASUK-nya job ke `download()`; tidak ada
    `sleep` sama sekali, jadi urutan bukti bersifat deterministik.
    """
    semaphore = asyncio.Semaphore(2)
    entered = [asyncio.Event() for _ in range(3)]
    release = [asyncio.Event() for _ in range(3)]
    collector = JobCollector()

    updates = [make_update(chat_id=1000 + i) for i in range(3)]
    contexts = [make_context(rl, settings, semaphore) for _ in range(3)]

    with (
        patch.object(downloader_service, "download", gated_download(settings, entered, release)),
        collector.install(),
    ):
        for update, context in zip(updates, contexts, strict=True):
            await download_handler(update, context)
        assert len(collector.tasks) == 3

        # dua slot pertama terisi; slot ketiga TIDAK boleh masuk sebelum ada pelepasan
        await asyncio.wait_for(entered[0].wait(), timeout=2.0)
        await asyncio.wait_for(entered[1].wait(), timeout=2.0)
        assert not entered[2].is_set(), "job ke-3 mulai padahal semaphore(2) masih penuh"
        assert semaphore.locked()  # tidak ada token tersisa

        # lepas satu slot -> job ke-3 baru boleh jalan
        release[0].set()
        await asyncio.wait_for(entered[2].wait(), timeout=2.0)

        for event in release:
            event.set()
        await collector.drain()

    # semua pengguna tetap dapat ack, tidak ada yang gagal karena antrian
    for update in updates:
        assert ACK_TEXT in reply_texts(update)
    assert len(entered) == 3 and all(e.is_set() for e in entered)


async def test_semaphore_value_follows_settings_not_hardcoded(tmp_path):
    """FR-010: `MAX_CONCURRENT_DOWNLOADS` dari env menentukan ukuran slot (default 2)."""
    sentinel = asyncio.Semaphore(1)
    entered = [asyncio.Event() for _ in range(2)]
    release = [asyncio.Event() for _ in range(2)]

    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial; hindari literal token
    conf = Settings.model_construct(
        telegram_bot_token=dummy_token,
        log_level="INFO",
        download_dir=str(tmp_path),
        max_file_size_mb=50,
        max_concurrent_downloads=1,
        rate_limit_window_seconds=10,
    )
    rl = UserRateLimiter(10)
    rl.time_source = lambda: 0.0
    collector = JobCollector()

    updates = [make_update(chat_id=2000 + i) for i in range(2)]
    contexts = [make_context(rl, conf, sentinel) for _ in range(2)]
    with (
        patch.object(downloader_service, "download", gated_download(conf, entered, release)),
        collector.install(),
    ):
        for update, context in zip(updates, contexts, strict=True):
            await download_handler(update, context)
        await asyncio.wait_for(entered[0].wait(), timeout=2.0)
        assert not entered[1].is_set(), "semaphore(1) seharusnya menahan job kedua"
        release[0].set()
        await asyncio.wait_for(entered[1].wait(), timeout=2.0)
        release[1].set()
        await collector.drain()


# ----------------------------------------------------------------- T-115 --


async def test_handler_acks_in_under_two_seconds_with_10s_download(settings, rl):
    """T-115 (NFR Performance): ack < 2 dtk walau `download()` mock delay 10 detik.

    `download()` mock menunggu `asyncio.Event` yang baru dilepas di akhir test,
    jadi 10 detik pekerjaan berat tidak pernah benar-benar ditunggu. Pengukuran
    hanya membungkus `await download_handler(...)` — tidak ada `sleep`.
    """
    hold = asyncio.Event()  # diset di akhir test; job tidak pernah jalan 10 dtk
    entered = [asyncio.Event() for _ in range(1)]

    async def slow_download(url: str, _settings: Settings) -> DownloadResult:
        entered[0].set()
        await asyncio.wait_for(hold.wait(), timeout=10)
        return fake_result(_settings)

    collector = JobCollector()
    update = make_update()
    context = make_context(rl, settings, asyncio.Semaphore(2))

    with (
        patch.object(downloader_service, "download", slow_download),
        collector.install(),
    ):
        started = time.monotonic()
        await download_handler(update, context)
        elapsed = time.monotonic() - started

        assert elapsed < 2.0, f"handler return {elapsed:.3f}s — melanggar ack < 2 dtk"
        assert reply_texts(update) == [ACK_TEXT]
        # ack mendahului pekerjaan berat: job di-spawn tapi download belum mulai
        assert not entered[0].is_set()

        # pekerjaan berat masih tertunda di latar belakang saat handler return
        assert collector.tasks and not collector.tasks[0].done()

        hold.set()
        await collector.drain()

    assert entered[0].is_set()
    assert context.bot.send_video.call_count == 1  # jalur normal selesai utuh


async def test_download_start_is_queued_not_inline(settings, rl):
    """T-113: antrian semaphore terjadi SETELAH ack, bukan menahan ack."""
    semaphore = asyncio.Semaphore(1)
    entered = [asyncio.Event() for _ in range(2)]
    release = [asyncio.Event() for _ in range(2)]
    collector = JobCollector()

    updates = [make_update(chat_id=3000 + i) for i in range(2)]
    contexts = [make_context(rl, settings, semaphore) for _ in range(2)]

    with (
        patch.object(downloader_service, "download", gated_download(settings, entered, release)),
        collector.install(),
    ):
        started = time.monotonic()
        for update, context in zip(updates, contexts, strict=True):
            await download_handler(update, context)
        elapsed = time.monotonic() - started

        # dua handler (termasuk yang harus antri di semaphore) tetap ack langsung
        assert elapsed < 2.0
        for update in updates:
            assert reply_texts(update) == [ACK_TEXT]

        await asyncio.wait_for(entered[0].wait(), timeout=2.0)
        assert not entered[1].is_set()
        release[0].set()
        release[1].set()
        await collector.drain()


# ----------------------------------------------------------------- T-116 --


async def test_one_failing_url_does_not_crash_the_loop(settings, rl, caplog):
    """T-116 (NFR Reliability, SC §8 butir 6): 1 URL gagal -> bot tetap hidup.

    Job gagal jalan lebih dulu, lalu job sukses: setelah kegagalan, bot harus
    masih melayani permintaan berikutnya (loop hidup, slot semaphore dilepas).
    """
    semaphore = asyncio.Semaphore(2)
    failing = make_update(chat_id=4001)
    failing_ctx = make_context(rl, settings, semaphore)

    async def boom(url: str, _settings: Settings) -> DownloadResult:
        raise DownloadFailedError("yt-dlp mati")

    collector = JobCollector()
    with (
        caplog.at_level(logging.ERROR, logger="app.handlers.download"),
        patch.object(downloader_service, "download", boom),
        collector.install(),
    ):
        await download_handler(failing, failing_ctx)
        await collector.drain()

        loop = asyncio.get_running_loop()
        assert not loop.is_closed(), "event loop mati setelah satu job gagal"
        assert all(task.done() and not task.cancelled() for task in collector.tasks)

    # pengguna: ack + pesan error bersih (bukan traceback / isi exception mentah)
    assert ACK_TEXT in reply_texts(failing)
    sent = [c.kwargs.get("text", "") for c in failing_ctx.bot.send_message.call_args_list]
    assert "⚠️ Gagal mengunduh." in sent
    assert not any("Traceback" in text or "yt-dlp mati" in text for text in sent)
    assert "yt-dlp mati" in caplog.text  # detail hanya ke log (AGENTS.md §5)

    # bot masih hidup: permintaan berikutnya tetap dilayani sampai upload
    async def ok(url: str, _settings: Settings) -> DownloadResult:
        return fake_result(_settings)

    next_update = make_update(chat_id=4002)
    next_ctx = make_context(rl, settings, semaphore)
    collector2 = JobCollector()
    with (
        patch.object(downloader_service, "download", ok),
        collector2.install(),
    ):
        await download_handler(next_update, next_ctx)
        await collector2.drain()
    assert ACK_TEXT in reply_texts(next_update)
    assert next_ctx.bot.send_video.call_count == 1


async def test_queue_survives_failure_and_frees_slot(settings, rl):
    """Gagal di dalam slot harus melepas semaphore — slot tidak pernah bocor."""
    semaphore = asyncio.Semaphore(1)
    collector = JobCollector()

    async def boom(url: str, _settings: Settings) -> DownloadResult:
        raise DownloadFailedError("gagal")

    async def ok(url: str, _settings: Settings) -> DownloadResult:
        return fake_result(_settings)

    contexts = [make_context(rl, settings, semaphore) for _ in range(2)]
    with patch.object(downloader_service, "download", boom), collector.install():
        await download_handler(make_update(chat_id=5001), contexts[0])
        await collector.drain()
    assert semaphore._value == 1, "slot tidak dilepas setelah kegagalan"

    with patch.object(downloader_service, "download", ok), collector.install():
        await download_handler(make_update(chat_id=5002), contexts[1])
        await collector.drain()
    assert contexts[1].bot.send_video.call_count == 1


def _assert_only_file(download_dir: str, name: str) -> None:
    """Helper sinkron: assert I/O tidak inline di coroutine (ruff ASYNC240)."""
    root = Path(download_dir)
    assert sorted(entry.name for entry in root.iterdir()) == [name]


def _assert_dir_empty(download_dir: str) -> None:
    assert list(Path(download_dir).iterdir()) == []


URL_A = "https://www.instagram.com/reel/aaaaa/"
URL_B = "https://www.instagram.com/reel/bbbbb/"


async def test_cleanup_never_wipes_a_concurrent_job_file(settings, rl):
    """Regresi deviasi WP-11: cleanup (FR-008) hanya jalan DI DALAM slot yang sama.

    Bila `clean_dir` berada di luar `async with semaphore:`, job yang selesai
    lebih dulu akan mengosongkan `download_dir` selagi job lain masih memakai
    slot yang sama -> file hasil download job kedua terhapus sebelum sempat
    di-upload (`FileNotFoundError` — kegagalan nyata pada implementasi pertama).
    Urutan yang dikunci: B tidak menyentuh `download()` sampai A melepas slot
    beserta cleanup-nya.
    """
    semaphore = asyncio.Semaphore(1)  # satu slot: B pasti menunggu A
    upload_entered = asyncio.Event()
    release_upload = asyncio.Event()
    started: list[str] = []
    finished: list[str] = []
    files: dict[str, asyncio.Event] = {}

    async def tracking_download(url: str, _settings: Settings) -> DownloadResult:
        name = "a.mp4" if url == URL_A else "b.mp4"
        started.append(name)
        path = Path(_settings.download_dir) / name
        path.write_bytes(b"x" * 32)
        files[name] = asyncio.Event()
        return DownloadResult(path=path, metadata={"title": name})

    def make_upload(label: str):
        async def _upload(**kwargs):
            started.append(label)
            await asyncio.wait_for(upload_entered.wait(), timeout=2.0)
            await release_upload.wait()
            finished.append(label)

        return _upload

    update_a = make_update(URL_A, chat_id=6001)
    context_a = make_context(rl, settings, semaphore)
    context_a.bot.send_video = make_upload("upload-a")
    update_b = make_update(URL_B, chat_id=6002)
    context_b = make_context(rl, settings, semaphore)
    context_b.bot.send_video = make_upload("upload-b")

    collector = JobCollector()
    with (
        patch.object(downloader_service, "download", tracking_download),
        collector.install(),
    ):
        await download_handler(update_a, context_a)
        upload_entered.set()  # buka gerbang upload agar A bisa masuk & lalu tertahan
        for _ in range(10):  # schedulenya: biarkan job A sampai tahan di release
            await asyncio.sleep(0)
        assert started == ["a.mp4", "upload-a"]

        # B datang saat A masih memegang slot (upload + cleanup belum jalan)
        await download_handler(update_b, context_b)
        assert "b.mp4" not in started, "B harus menunggu slot A dilepas"
        _assert_only_file(settings.download_dir, "a.mp4")

        release_upload.set()
        await collector.drain()

    assert started == ["a.mp4", "upload-a", "b.mp4", "upload-b"]
    assert finished == ["upload-a", "upload-b"]
    _assert_dir_empty(settings.download_dir)  # FR-008: kedua job selesai -> bersih


# ----------------------------------------------------------------- T-111 --


async def test_main_stores_semaphore_in_bot_data(tmp_path, monkeypatch):
    """T-111 (FR-010, NFR Reliability): semaphore dibuat saat startup, per event loop."""
    from pydantic import SecretStr

    from app import main as main_mod

    conf = Settings.model_construct(
        telegram_bot_token=SecretStr("dummy token"),
        log_level="INFO",
        download_dir=str(tmp_path),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
    )
    application = MagicMock()
    application.bot_data = {}
    application.initialize = AsyncMock()
    application.start = AsyncMock()
    application.updater.start_polling = AsyncMock()

    builder = MagicMock()
    builder.token.return_value.build.return_value = application
    fake_application = MagicMock()
    fake_application.builder.return_value = builder
    monkeypatch.setattr(main_mod, "Application", fake_application)
    monkeypatch.setattr(main_mod, "get_settings", lambda: conf)

    run = asyncio.create_task(main_mod.main())
    for _ in range(10):  # beri main() jalan sampai macet di `await Event().wait()`
        await asyncio.sleep(0)
        if application.updater.start_polling.await_count:
            break
    assert application.updater.start_polling.await_count == 1

    semaphore = application.bot_data["semaphore"]
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == conf.max_concurrent_downloads == 2
    assert application.bot_data["settings"] is conf

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run


async def test_semaphore_is_not_module_level_global():
    """Anti-pattern: semaphore TIDAK boleh jadi global module-level (T-111)."""
    assert not hasattr(download_mod, "semaphore"), "semaphore module-level lintas event-loop"
    from app import main as main_mod

    assert not hasattr(main_mod, "semaphore")
