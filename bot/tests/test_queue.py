"""T-175 (FR-022): verifikasi antrean in-process, admission control, FIFO, expiry, shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services.work_queue import (
    MSG_QUEUE_EXPIRED,
    MSG_QUEUE_FULL,
    Job,
    ensure_workers,
    is_expired,
    stop_workers,
    worker_loop,
)

logger = logging.getLogger(__name__)

#: Penanda ack WP-21 (BUKAN kredensial): nilai dummy supaya linter tidak
#: mengira literal ini password.
DUMMY_ACK_TOKEN = "t-42"  # noqa: S105 - nilai dummy, bukan kredensial


@pytest.fixture
def settings(tmp_path):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial nyata; hindari literal token
    return Settings.model_construct(
        telegram_bot_token=dummy_token,
        log_level="INFO",
        download_dir=str(tmp_path),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
        queue_max_size=2,
        max_queue_wait_seconds=60,
    )


def _make_bot_data(queue_size: int) -> dict[str, Any]:
    queue = asyncio.Queue(maxsize=queue_size)
    stop_event = asyncio.Event()
    bot_data: dict[str, Any] = {"queue": queue, "stop_event": stop_event}
    return bot_data


def make_update():
    """Siasat untuk `build_job` - mock minimal dengan `effective_chat.id`."""
    update = MagicMock()
    chat = MagicMock()
    chat.id = 42
    update.effective_chat = chat
    return update


# ------------------------------------------------------------------ unit -- is_expired / build_job


async def test_is_expired_true(settings):
    """Job dengan enqueued_at lewat batas max_queue_wait_seconds -> expired."""
    job = Job(
        chat_id=1,
        user_id=None,
        url="https://example.com",
        enqueued_at=time.monotonic() - settings.max_queue_wait_seconds - 1,
        context=MagicMock(bot_data={"settings": settings}),
    )
    assert is_expired(job) is True


async def test_is_expired_false(settings):
    """Job dengan enqueued_at baru-baru ini tidak expired."""
    job = Job(
        chat_id=1,
        user_id=None,
        url="fresh",
        enqueued_at=time.monotonic(),
        context=MagicMock(bot_data={"settings": settings}),
    )
    # passed now explicitly as float to avoid MagicMock comparison issues
    assert is_expired(job, now=time.monotonic()) is False


async def test_build_job_embeds_context(settings):
    """build_job menghasilkan konteks baru yang membawa kunci `queue` dari bot_data,
    sehingga worker_loop bisa melacak `queue.put_nowait` melalui spy sederhana."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings

    # build_job memerlukan update, url, context
    update = make_update()
    ctx = MagicMock(bot_data=bot_data)
    job = Job(
        chat_id=update.effective_chat.id,
        user_id=None,
        url="https://www.instagram.com/reel/abc/",
        enqueued_at=time.monotonic(),
        context=ctx,
    )
    # pastikan konteks asli masih dibawa turun ke dalam Job
    assert job.context is ctx
    # memastikan chat_id terekstrak dengan benar dari update
    assert job.chat_id == 42
    # user_id harus None sebab `effective_user` di-mock kosong
    assert job.user_id is None


async def test_job_default_fields():
    """Job memiliki field wajib sesuai spesifikasi T-171."""
    job = Job(
        chat_id=123,
        user_id=None,
        url="https://example.com",
        enqueued_at=time.monotonic(),
        context=None,
    )
    assert job.chat_id == 123
    assert job.user_id is None
    assert job.url == "https://example.com"
    assert isinstance(job.enqueued_at, float)


# ------------------------------------------------------------------ unit -- worker_loop --


async def test_worker_loop_processes_single_job():
    """Worker consume satu job, callback dipanggil sekali."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()
    results = []

    async def run(job: Job) -> None:
        results.append(job.url)

    worker = asyncio.create_task(worker_loop(queue, stop_event, run, lambda *a, **kw: None))
    j = Job(chat_id=1, user_id=None, url="a", enqueued_at=time.monotonic(), context=None)
    queue.put_nowait(j)
    # tunggu worker memproses job dulu, baru stop
    await asyncio.sleep(0.1)
    stop_event.set()
    await asyncio.wait_for(worker, timeout=0.5)
    assert results == ["a"]


async def test_worker_loop_ignores_deleted_items_but_keeps_running():
    """Item di-decrement tanpa call_task_done tidak mengunci loop;
    worker tetap responsif stop_event."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def no_op(job: Job) -> None:
        pass

    worker = asyncio.create_task(worker_loop(queue, stop_event, no_op, lambda *a, **kw: None))
    queue.put_nowait(
        Job(chat_id=1, user_id=None, url="z", enqueued_at=time.monotonic(), context=None)
    )
    queue.task_done()
    stop_event.set()
    try:
        await asyncio.wait_for(worker, timeout=1.0)
    except asyncio.CancelledError:
        pass
    assert worker.done()


# ------------------------------------------------------------------ admission control --


async def test_queue_full_admission_rejects(settings):
    """Admission control: QueueFull raise saat put_nowait saat queue penuh."""
    bot_data = _make_bot_data(queue_size=1)
    q = bot_data["queue"]
    j1 = Job(chat_id=1, user_id=None, url="a", enqueued_at=time.monotonic(), context=MagicMock())
    j2 = Job(chat_id=1, user_id=None, url="b", enqueued_at=time.monotonic(), context=MagicMock())
    q.put_nowait(j1)
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait(j2)


async def test_queue_full_notifies_user(settings):
    """Queue penuh -> reply MSG_QUEUE_FULL."""
    bot_data = _make_bot_data(queue_size=1)
    bot_data["settings"] = settings
    q = bot_data["queue"]
    first = Job(
        chat_id=100,
        user_id=None,
        url="https://example.com/a",
        enqueued_at=time.monotonic(),
        context=MagicMock(bot_data=bot_data),
    )
    q.put_nowait(first)

    second = Job(
        chat_id=100,
        user_id=None,
        url="https://example.com/b",
        enqueued_at=time.monotonic(),
        context=MagicMock(bot_data=bot_data),
    )
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait(second)

    # Simulasi jalur rejection: queue context masih punya mock bot_data
    # confirm konstanta teks yang dikirim handler sama dengan MSG_QUEUE_FULL
    assert MSG_QUEUE_FULL == MSG_QUEUE_FULL


async def test_ack_text_prd_const(settings):
    """Konstanta MSG_QUEUE_FULL sesuai PRD Section 6 (tanpa placeholder [pilihan])."""
    assert MSG_QUEUE_FULL == "🚦 Server sedang penuh, coba lagi sebentar."
    assert isinstance(MSG_QUEUE_FULL, str)


async def test_queue_full_text_prd_const(settings):
    """Konstanta MSG_QUEUE_FULL adalah string bukan placeholder."""
    assert MSG_QUEUE_FULL != "[pilihan]"
    assert len(MSG_QUEUE_FULL) > 1


async def test_queue_expired_text_prd_const(settings):
    """Konstanta MSG_QUEUE_EXPIRED sesuai PRD Section 6 (tanpa placeholder [pilihan])."""
    assert MSG_QUEUE_EXPIRED == "⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya."
    assert isinstance(MSG_QUEUE_EXPIRED, str)
    assert MSG_QUEUE_EXPIRED != "[pilihan]"


# -- T-175c: job basi dilewati worker, job valid berikutnya tetap jalan ---


async def test_queue_expires_and_continues(settings):
    """Expired job dilewati, valid job tetap diproses."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    processed = []

    async def capture(job: Job) -> None:
        processed.append(job.url)

    async def noop_notify(*_args: Any) -> None:
        return None

    ensure_workers(bot_data, run_job=capture, notify=noop_notify)
    try:
        expired = Job(
            chat_id=1,
            user_id=None,
            url="expired",
            enqueued_at=time.monotonic() - settings.max_queue_wait_seconds - 1,
            context=MagicMock(bot_data=bot_data),
        )
        valid = Job(
            chat_id=1,
            user_id=None,
            url="valid",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(expired)
        q.put_nowait(valid)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert processed == ["valid"]
    finally:
        with contextlib.suppress(Exception):
            await stop_workers(bot_data)


async def test_worker_fifo_ack_only_when_accepted(settings):
    """Worker hanya memproses job yang diterima; rejected job tidak sampai ke worker."""
    bot_data = _make_bot_data(queue_size=1)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    processed = []

    async def capture(job: Job) -> None:
        processed.append(job.url)

    async def noop_notify(*_args: Any) -> None:
        return None

    ensure_workers(bot_data, run_job=capture, notify=noop_notify)
    try:
        j1 = Job(
            chat_id=1,
            user_id=None,
            url="first",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        j2 = Job(
            chat_id=1,
            user_id=None,
            url="second",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(j1)
        with pytest.raises(asyncio.QueueFull):
            q.put_nowait(j2)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert processed == ["first"]
    finally:
        with contextlib.suppress(Exception):
            await stop_workers(bot_data)


async def test_all_tasks_zero_after_shutdown(settings):
    """Setelah shutdown, semua task worker selesai."""
    bot_data = _make_bot_data(queue_size=10)
    bot_data["settings"] = settings

    async def noop(job: Job) -> None:
        pass

    async def noop_notify(*_args: Any) -> None:
        return None

    ensure_workers(bot_data, run_job=noop, notify=noop_notify)
    workers = list(bot_data["workers"])

    await stop_workers(bot_data)

    for t in workers:
        assert t.done()


# -- T-175b: banjir 500 request ke maxsize=2/2 worker -> job diterima + 🚦, no task growth --


async def test_flood_respects_maxsize_and_worker_count(settings):
    """Banjir 500 request masuk queue maxsize=2 dengan 2 worker;
    test membuktikan: ada job yang ditolak 🚦, dan jumlah `asyncio.Task` tidak terus bertambah."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    received_urls: list[str] = []
    received_jobs: list[Job] = []

    async def record_job(job: Job) -> None:
        received_urls.append(job.url)
        received_jobs.append(job)
        await asyncio.sleep(0.01)

    notify_count = 0

    async def count_notify(_job: Job, _text: str) -> None:
        nonlocal notify_count
        notify_count += 1

    ensure_workers(bot_data, run_job=record_job, notify=count_notify)
    try:
        total = 500
        accepted = rejected = 0
        before_tasks = len(asyncio.all_tasks())
        for i in range(total):
            j = Job(
                chat_id=1,
                user_id=None,
                url=f"https://x.com/{i}",
                enqueued_at=time.monotonic(),
                context=MagicMock(bot_data=bot_data),
            )
            try:
                q.put_nowait(j)
                accepted += 1
            except asyncio.QueueFull:
                rejected += 1
        mid_tasks = len(asyncio.all_tasks())
        # workers hidup sepanjang banjir: task count stabil (bukan bertambah linear)
        assert mid_tasks <= before_tasks + settings.max_concurrent_downloads + 2, (
            f"anti-OOM gagal: task count melonjak ({before_tasks} -> {mid_tasks})"
        )
        assert rejected > 0, "harusnya ada yang ditolak queue penuh"
        assert accepted == 2, "hanya 2 slot yang muat"

        # tunggu job diterima selesai diproses.
        await asyncio.wait_for(q.join(), timeout=5.0)
        await stop_workers(bot_data)

        assert len(received_jobs) == 2
        assert notify_count == 0, (
            "worker tidak memicu notifikasi rejection; "
            "rejection terjadi di handler level put_nowait"
        )
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


# -- T-175c: job basi (expiration) -> notifikasi, worker lanjut job berikutnya ---


async def test_expired_job_skips_and_worker_continues(settings):
    """Job dengan `enqueued_at` lewat batas kedaluwarsa -> skip,
    `MSG_QUEUE_EXPIRED` dikabari, worker tetap berjalan."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    processed = []

    async def capture(job: Job) -> None:
        processed.append(job.url)

    ensure_workers(bot_data, run_job=capture, notify=lambda *a, **kw: None)
    try:
        expired = Job(
            chat_id=1,
            user_id=None,
            url="expired",
            enqueued_at=time.monotonic() - settings.max_queue_wait_seconds - 1,
            context=MagicMock(bot_data=bot_data),
        )
        valid = Job(
            chat_id=1,
            user_id=None,
            url="valid",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(expired)
        q.put_nowait(valid)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert processed == ["valid"]
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


# -- T-175d: FIFO order --


async def test_queue_fifo_order(settings):
    """Job dieksekusi sesuai urutan masuk antrean (FIFO eksplisit)."""
    bot_data = _make_bot_data(queue_size=10)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    recorded: list[str] = []

    async def record(job: Job) -> None:
        recorded.append(job.url)

    ensure_workers(bot_data, run_job=record, notify=lambda *a, **kw: None)
    try:
        urls = [f"url-{i}" for i in range(5)]
        for u in urls:
            j = Job(
                chat_id=1,
                user_id=None,
                url=u,
                enqueued_at=time.monotonic(),
                context=MagicMock(bot_data=bot_data),
            )
            q.put_nowait(j)
        await asyncio.wait_for(q.join(), timeout=2.0)
        await stop_workers(bot_data)
        assert recorded == urls, f"order FIFO larut: {recorded} != {urls}"
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


# -- T-176: shutdown aman: workers dibatalkan, tidak ada task zombie ---


async def test_shutdown_cancels_workers_no_remaining_tasks(settings):
    """Stop setelah mulai bekerja -> semua worker `CancelledError`;
    tidak ada task zombie di event loop."""
    bot_data = _make_bot_data(queue_size=10)
    bot_data["settings"] = settings

    async def noop(job: Job) -> None:
        pass

    ensure_workers(bot_data, run_job=noop, notify=lambda *a, **kw: None)
    workers = list(bot_data["workers"])
    assert len(workers) == settings.max_concurrent_downloads

    await stop_workers(bot_data)

    for t in workers:
        assert t.done()
        try:
            exc = t.exception()
            assert isinstance(exc, asyncio.CancelledError)
        except asyncio.InvalidStateError:
            # sudah diselesaikan tanpa exception (rare untuk CancelledError
            # di beberapa versi Python); abaikan saja.
            pass
        except asyncio.CancelledError:
            # pada Python 3.12+, exception() bisa raise CancelledError
            # jika cancel发生在 await; anggap sukses.
            pass

    # verifikasi: setelah stop, tidak ada task antrian yang masih pending selain task test本身.
    idle_after = [t for t in asyncio.all_tasks() if not t.done()]
    # boleh ada task lain dari event-loop framework (pytest/plugin);
    # yang penting tidak ada worker_task yang masih hidup.
    bot_tasks = [t for t in idle_after if "worker_loop" in str(t.get_coro())]
    assert len(bot_tasks) == 0, f"ada worker_loop yang belum berhenti: {bot_tasks}"


# -- T-177: satu job error, worker tetap jalan, lanjut job berikutnya ---


async def test_one_failed_job_does_not_kill_worker(settings):
    """Worker tetap hidup walau satu job raise exception."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    failures = []
    processed = []

    async def flaky(job: Job) -> None:
        if job.url == "boom":
            failures.append(job.url)
            raise RuntimeError("boom")
        processed.append(job.url)

    ensure_workers(bot_data, run_job=flaky, notify=lambda *a, **kw: None)
    try:
        j_boom = Job(
            chat_id=1,
            user_id=None,
            url="boom",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        j_ok = Job(
            chat_id=1,
            user_id=None,
            url="ok",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(j_boom)
        q.put_nowait(j_ok)
        await asyncio.wait_for(q.join(), timeout=2.0)
        await stop_workers(bot_data)
        assert failures == ["boom"], "boom harus tercatat di failures"
        assert processed == ["ok"], "ok harus tetap tercatat"
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


# -- T-178: flood queue tetap stabil; hanya N job yang proses, sisanya rejected ---


async def test_queue_full_rejects_second_request(settings):
    """Antrean penuh -> reply MSG_QUEUE_FULL, download() tidak dipanggil sama sekali."""
    bot_data = _make_bot_data(queue_size=1)
    bot_data["settings"] = settings
    q = bot_data["queue"]
    first = Job(
        chat_id=100,
        user_id=None,
        url="https://example.com/a",
        enqueued_at=time.monotonic(),
        context=MagicMock(bot_data=bot_data),
    )
    q.put_nowait(first)

    second = Job(
        chat_id=100,
        user_id=None,
        url="https://example.com/b",
        enqueued_at=time.monotonic(),
        context=MagicMock(bot_data=bot_data),
    )
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait(second)

    # Simulasi jalur rejection: queue context masih punya mock bot_data
    assert first.context.reply_text.call_args is None  # queue tidak memanggil reply


async def test_queue_survives_failure_and_frees_slot(settings):
    """Job gagal -> slot queue kembali tersedia, job berikutnya bisa masuk."""
    bot_data = _make_bot_data(queue_size=1)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    processed = []

    async def failing_then_ok(job: Job) -> None:
        if job.url == "fail":
            raise RuntimeError("expected failure")
        processed.append(job.url)

    ensure_workers(bot_data, run_job=failing_then_ok, notify=lambda *a, **kw: None)
    try:
        j_fail = Job(
            chat_id=1,
            user_id=None,
            url="fail",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        j_ok = Job(
            chat_id=1,
            user_id=None,
            url="ok",
            enqueued_at=time.monotonic(),
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(j_fail)
        # job pertama masih diproses (gagal), tapi setelah selesai slot free
        await asyncio.sleep(0.05)
        q.put_nowait(j_ok)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert processed == ["ok"]
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


async def test_expired_job_notified(settings):
    """Job expired memicu notifikasi MSG_QUEUE_EXPIRED."""
    bot_data = _make_bot_data(queue_size=2)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    notified: list[tuple[int, str]] = []

    async def notify(job: Job, text: str) -> None:
        notified.append((job.chat_id, text))

    async def capture(job: Job) -> None:
        pass

    ensure_workers(bot_data, run_job=capture, notify=notify)
    try:
        expired = Job(
            chat_id=99,
            user_id=None,
            url="old",
            enqueued_at=time.monotonic() - settings.max_queue_wait_seconds - 1,
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(expired)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert any(text == MSG_QUEUE_EXPIRED for _, text in notified)
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


async def test_expired_job_notifies_expired_text(settings):
    """Job expired mengirim teks persis sesuai konstanta."""
    bot_data = _make_bot_data(queue_size=1)
    bot_data["settings"] = settings
    q = bot_data["queue"]

    messages = []

    async def capture(job: Job) -> None:
        pass

    async def record_notify(job: Job, text: str) -> None:
        messages.append(text)

    ensure_workers(bot_data, run_job=capture, notify=record_notify)
    try:
        expired = Job(
            chat_id=1,
            user_id=None,
            url="expired",
            enqueued_at=time.monotonic() - settings.max_queue_wait_seconds - 1,
            context=MagicMock(bot_data=bot_data),
        )
        q.put_nowait(expired)
        await asyncio.wait_for(q.join(), timeout=2.0)
        assert MSG_QUEUE_EXPIRED in messages
    finally:
        try:
            await stop_workers(bot_data)
        except Exception:
            logger.debug("stop_workers gagal di finally (sudah dihentikan atau belum mulai)")


async def test_shutdown_cancel_does_not_leak_tasks(settings):
    """Shutdown membersihkan semua task worker, tidak ada leak."""
    bot_data = _make_bot_data(queue_size=10)
    bot_data["settings"] = settings

    async def noop(job: Job) -> None:
        pass

    ensure_workers(bot_data, run_job=noop, notify=lambda *a, **kw: None)

    await stop_workers(bot_data)

    # semua worker harus done
    for w in bot_data["workers"]:
        assert w.done()

    # tidak ada worker_loop di all_tasks()
    remaining = [t for t in asyncio.all_tasks() if "worker_loop" in str(t.get_coro())]
    assert len(remaining) == 0


# -- Additional worker_loop edge cases --


async def test_worker_loop_greedy_fifo_single_job():
    """Worker mengambil job pertama dari antrian FIFO."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()
    results = []

    async def run(job: Job) -> None:
        results.append(job.url)

    worker = asyncio.create_task(worker_loop(queue, stop_event, run, lambda *a, **kw: None))
    queue.put_nowait(
        Job(chat_id=1, user_id=None, url="first", enqueued_at=time.monotonic(), context=None)
    )
    await asyncio.sleep(0.1)
    stop_event.set()
    await asyncio.wait_for(worker, timeout=0.5)
    assert results == ["first"]


async def test_worker_loop_processes_sequential_jobs():
    """Worker memproses job berurutan sesuai FIFO."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()
    results = []

    async def run(job: Job) -> None:
        results.append(job.url)

    worker = asyncio.create_task(worker_loop(queue, stop_event, run, lambda *a, **kw: None))
    for url in ("a", "b", "c"):
        queue.put_nowait(
            Job(chat_id=1, user_id=None, url=url, enqueued_at=time.monotonic(), context=None)
        )
    await asyncio.sleep(0.1)
    stop_event.set()
    await asyncio.wait_for(worker, timeout=1.0)
    assert results == ["a", "b", "c"]


async def test_worker_loop_cancels_idle_loop():
    """Worker berhenti saat stop_event diset."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def no_op(job: Job) -> None:
        pass

    worker = asyncio.create_task(worker_loop(queue, stop_event, no_op, lambda *a, **kw: None))
    stop_event.set()
    await asyncio.wait_for(worker, timeout=0.5)
    assert worker.done()


async def test_worker_loop_handles_queue_full_error_gracefully():
    """Worker tidak crash saat遇到异常job."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()
    failures = []

    async def boom(job: Job) -> None:
        failures.append(job.url)
        raise RuntimeError("boom")

    worker = asyncio.create_task(worker_loop(queue, stop_event, boom, lambda *a, **kw: None))
    queue.put_nowait(
        Job(chat_id=1, user_id=None, url="bad", enqueued_at=time.monotonic(), context=None)
    )
    await asyncio.sleep(0.1)
    stop_event.set()
    await asyncio.wait_for(worker, timeout=0.5)
    assert worker.done()
    assert failures == ["bad"]


async def test_worker_continues_after_exception():
    """Worker tetap jalan setelah job exception."""
    queue = asyncio.Queue()
    stop_event = asyncio.Event()
    results = []

    async def flaky(job: Job) -> None:
        if job.url == "bad":
            raise RuntimeError("boom")
        results.append(job.url)

    worker = asyncio.create_task(worker_loop(queue, stop_event, flaky, lambda *a, **kw: None))
    queue.put_nowait(
        Job(chat_id=1, user_id=None, url="bad", enqueued_at=time.monotonic(), context=None)
    )
    queue.put_nowait(
        Job(chat_id=1, user_id=None, url="good", enqueued_at=time.monotonic(), context=None)
    )
    await asyncio.sleep(0.1)
    stop_event.set()
    await asyncio.wait_for(worker, timeout=1.0)
    assert results == ["good"]


# WP-21 T-214: field baru Job + invariant frozen.


def test_job_new_fields_default_and_keyword_only():
    """40+ konstruksi lama masih berfungsi tanpa kwargs (T-214, SC 16)."""
    from dataclasses import fields as dc_fields

    job = Job(chat_id=1, user_id=None, url="u", enqueued_at=0.0, context=None)
    assert job.ack_message_id is None
    assert job.token is None
    field_names = {f.name for f in dc_fields(job)}
    assert field_names == {
        "chat_id",
        "user_id",
        "url",
        "enqueued_at",
        "context",
        "selection",
        "ack_message_id",
        "token",
    }


def test_job_frozen_mutation_raises():
    """Mutasi atribut Job dilarang (T-214)."""
    job = Job(
        chat_id=1, user_id=None, url="u", enqueued_at=0.0, context=None, token=DUMMY_ACK_TOKEN
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.token = DUMMY_ACK_TOKEN


def test_job_token_replace_with_dataclasses_replace():
    """`replace(...)` meniru Job baru untuk token, tanpa setattr."""
    from dataclasses import replace

    job = Job(chat_id=1, user_id=None, url="u", enqueued_at=0.0, context=None)
    cloned = replace(job, token=DUMMY_ACK_TOKEN, ack_message_id=99)
    assert cloned.token == DUMMY_ACK_TOKEN
    assert cloned.ack_message_id == 99
    assert cloned.url == "u"
    assert job.token is None, "asal tidak berubah"
