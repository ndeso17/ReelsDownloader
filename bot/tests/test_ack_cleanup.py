"""WP-21 (T-216): ack `⏳ Sedang memproses...` WAJIB hilang di semua terminal state.

Mock-only, TANPA jaringan Telegram (AGENTS §5: test tidak boleh menembak
jaringan). Bukti akar masalah yang direproduksi di sini:

1. `download.py` dulu mengirim ack tanpa menyimpan `message_id`, dan
   `grep -rn "delete_message" app/` KOSONG -> ack menggantung selamanya.
2. Test (a) di bawah GAGAL di HEAD sebelum patch (tidak ada `delete_message`),
   dan HIJAU sesudah - itulah bukti regresi diperbaiki, bukan fitur baru.

Cakupan (a)..(f) sesuai PLAN WP-21 T-216.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest

from app.config import Settings
from app.handlers import download as download_mod
from app.handlers.download import download_handler
from app.services import downloader as downloader_service
from app.services.downloader import DownloadResult
from app.services.errors import UploadError
from app.services.rate_limiter import UserRateLimiter
from app.services.work_queue import Job, worker_loop
from tests.queue_support import JobCollector, block_workers

VALID_URL = "https://www.instagram.com/reel/xxxxx/"
CHAT_ID = 123456
ACK_MESSAGE_ID = 777


# ------------------------------- fixtures ----------------------------------


@pytest.fixture
def settings(tmp_path) -> Settings:
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
        queue_max_size=5,
        max_queue_wait_seconds=60,
    )


@pytest.fixture
def rl() -> UserRateLimiter:
    limiter = UserRateLimiter(10)
    limiter.time_source = lambda: 0.0
    return limiter


def make_update(text: str, chat_id: int = CHAT_ID) -> MagicMock:
    """Update tiruan + `reply_text` yang mengembalikan pesan ber-`message_id`."""
    message = MagicMock()
    message.text = text
    ack = MagicMock()
    ack.message_id = ACK_MESSAGE_ID
    message.reply_text = AsyncMock(return_value=ack)
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


def make_context(rl: UserRateLimiter, settings: Settings, *, delete_error: Exception | None = None):
    """Context tiruan; `delete_message` AsyncMock (ops. selalu melempar)."""
    context = MagicMock()
    context.bot_data = {"rate_limiter": rl, "settings": settings}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    if delete_error is None:
        context.bot.delete_message = AsyncMock()
    else:
        context.bot.delete_message = AsyncMock(side_effect=delete_error)
    return context


def _ok_result(settings: Settings) -> DownloadResult:
    """`DownloadResult` yang lolos `sanitize_metadata` (metadata dict nyata)."""
    return DownloadResult(
        path=Path(settings.download_dir) / "x.mp4",
        metadata={"title": "video"},
    )


def _queue_acked_job(settings: Settings) -> Job:
    """Job berpenanda ack, tanpa worker: bahan uji `run_job` langsung.

    `enqueued_at` = `time.monotonic()` (BUKAN 0.0) supaya `is_expired` false dan
    worker benar-benar menjalankan job, bukan membuangnya sebagai kedaluwarsa.
    """
    return Job(
        chat_id=CHAT_ID,
        user_id=1,
        url=VALID_URL,
        enqueued_at=time.monotonic(),
        context=None,
        ack_message_id=ACK_MESSAGE_ID,
        token="t-1",  # noqa: S106 - penanda job, bukan kredensial
    )


# --------- (a) sukses upload -> delete_message tepat sekali, id benar --------


async def test_ack_deleted_once_on_success(rl, settings):
    collector = JobCollector(worker_count=1)
    update = make_update(VALID_URL)
    context = make_context(rl, settings)

    with (
        collector.install(),
        patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))),
        patch.object(download_mod, "send_video", AsyncMock(return_value=True)),
    ):
        await download_handler(update, context)
        # `reply_text` mengembalikan pesan BER-message_id -> tercatat di registry.
        assert context.bot_data["ack_messages"][CHAT_ID] == ACK_MESSAGE_ID
        await collector.drain()

    assert context.bot.delete_message.await_count == 1, "ack dihapus TEPAT sekali"
    kwargs = context.bot.delete_message.await_args.kwargs
    assert kwargs["chat_id"] == CHAT_ID
    assert kwargs["message_id"] == ACK_MESSAGE_ID
    # Idempoten: registry sudah bersih, jadi jalur lain tidak menghapus dua kali.
    assert CHAT_ID not in context.bot_data["ack_messages"]


# --------- (b) gagal download -> tetap dihapus di `finally` -----------------


async def test_ack_deleted_when_download_fails(rl, settings, caplog):
    collector = JobCollector(worker_count=1)
    update = make_update(VALID_URL)
    context = make_context(rl, settings)

    with (
        collector.install(),
        patch.object(downloader_service, "download", AsyncMock(side_effect=RuntimeError("boom"))),
        caplog.at_level("ERROR"),
    ):
        await download_handler(update, context)
        await collector.drain()

    assert context.bot.delete_message.await_count == 1
    assert context.bot.delete_message.await_args.kwargs["message_id"] == ACK_MESSAGE_ID
    assert CHAT_ID not in context.bot_data["ack_messages"]


# --------- (c) gagal upload (UploadError) -> tetap dihapus ------------------


async def test_ack_deleted_when_upload_fails(rl, settings):
    collector = JobCollector(worker_count=1)
    update = make_update(VALID_URL)
    context = make_context(rl, settings)

    with (
        collector.install(),
        patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))),
        patch.object(download_mod, "send_video", AsyncMock(side_effect=UploadError("nope"))),
    ):
        await download_handler(update, context)
        await collector.drain()

    assert context.bot.delete_message.await_count == 1
    assert context.bot.delete_message.await_args.kwargs["message_id"] == ACK_MESSAGE_ID


# --------- (d) delete_message melempar BadRequest -> run_job tidak raise ----


async def test_bad_request_on_delete_does_not_kill_worker(rl, settings, caplog):
    """Ack basi (`Message to delete not found`) tidak boleh membunuh worker.

    Dua lapis bukti: (1) `run_job` selesai normal walau `delete_message`
    melempar `BadRequest`, dan (2) `worker_loop` tetap memproses job berikutnya
    (NFR Reliability) - job dengan ack basi tidak boleh menghentikan worker.
    """
    context = make_context(rl, settings, delete_error=BadRequest("Message to delete not found"))
    context.bot_data["ack_messages"] = {CHAT_ID: ACK_MESSAGE_ID}
    job = _queue_acked_job(settings)

    with (
        patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))),
        patch.object(download_mod, "send_video", AsyncMock(return_value=True)),
        caplog.at_level("WARNING"),
    ):
        # (1) `run_job` tidak raise walau `delete_message` melempar BadRequest.
        uploaded = await download_mod.run_job(job, context, settings)

    assert uploaded is True, "upload tetap tersampaikan meski hapus ack gagal"
    assert context.bot.delete_message.await_count == 1
    assert any("hapus pesan ack gagal" in r.message for r in caplog.records)

    # (2) `worker_loop` tetap hidup: dua job berurutan selesai tanpa macet.
    queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    stop_event = asyncio.Event()
    processed: list[str] = []

    async def run_job_spy(j, *args, **kwargs):
        processed.append(j.url)
        return await download_mod.run_job(j, context, settings)

    with patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))):
        task = asyncio.create_task(worker_loop(queue, stop_event, run_job_spy, AsyncMock()))
        queue.put_nowait(job)
        queue.put_nowait(_queue_acked_job(settings))
        await asyncio.wait_for(queue.join(), timeout=5.0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=5.0)

    assert processed == [VALID_URL, VALID_URL], "worker memproses job berikutnya"
    assert not task.cancelled(), "worker tidak mati karena ack basi"


# --------- (e) job kedaluwarsa -> tidak ada ack menggantung -----------------


async def test_expired_job_deletes_ack(rl, settings):
    """Jalur `_notify_chat` (kedaluwarsa) juga membersihkan ack (T-216e)."""
    context = make_context(rl, settings)
    context.bot_data["ack_messages"] = {CHAT_ID: ACK_MESSAGE_ID}
    job = Job(
        chat_id=CHAT_ID,
        user_id=1,
        url=VALID_URL,
        enqueued_at=0.0,
        context=context,
        ack_message_id=ACK_MESSAGE_ID,
        token="t-exp",  # noqa: S106 - penanda job, bukan kredensial
    )
    context.bot_data["ack_tokens"] = {"t-exp": (CHAT_ID, ACK_MESSAGE_ID)}

    await download_mod._notify_chat(job, "⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.")

    assert context.bot.delete_message.await_count == 1
    assert context.bot.delete_message.await_args.kwargs["message_id"] == ACK_MESSAGE_ID
    assert CHAT_ID not in context.bot_data["ack_messages"]
    assert "t-exp" not in context.bot_data["ack_tokens"]
    # Pesan kedaluwarsa tetap terkirim (teks tidak berubah, PRD §6).
    assert context.bot.send_message.await_args.kwargs["text"].startswith("⌛")


# --------- (f) tombol Batalkan -> jawab callback, antrean job lain aman -----


def make_callback(token: str, chat_id: int = CHAT_ID) -> MagicMock:
    query = MagicMock()
    query.data = f"ac:{token}"
    query.answer = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    return update


async def test_cancel_button_removes_only_its_job(rl, settings):
    """Callback `ac:<token>` mengeluarkan job miliknya saja, ack-nya dihapus."""
    context = make_context(rl, settings)
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    other = Job(
        chat_id=999,
        user_id=1,
        url="u-other",
        enqueued_at=0.0,
        context=context,
        token="keep",  # noqa: S106 - penanda job, bukan kredensial
    )
    mine = Job(
        chat_id=CHAT_ID,
        user_id=1,
        url=VALID_URL,
        enqueued_at=0.0,
        context=context,
        token="t-mine",  # noqa: S106 - penanda job, bukan kredensial
        ack_message_id=ACK_MESSAGE_ID,
    )
    queue.put_nowait(other)
    queue.put_nowait(mine)
    context.bot_data["queue"] = queue
    context.bot_data["task_counter"] = [2]
    context.bot_data["ack_messages"] = {CHAT_ID: ACK_MESSAGE_ID}
    context.bot_data["ack_tokens"] = {"t-mine": (CHAT_ID, ACK_MESSAGE_ID)}

    await download_mod.cancel_ack_callback(make_callback("t-mine"), context)

    # Antrean hanya menyisakan job lain.
    remaining = []
    while not queue.empty():
        remaining.append(queue.get_nowait())
    assert [j.token for j in remaining] == ["keep"], "job lain tidak tersentuh"
    assert context.bot.delete_message.await_count == 1
    assert context.bot_data["task_counter"] == [1], "counter kerja dilepas"
    assert "t-mine" not in context.bot_data["ack_tokens"]


async def test_cancel_button_answers_callback(rl, settings):
    """`answer()` tepat sekali dengan pesan halus (PRD §3: tanpa spinner)."""
    context = make_context(rl, settings)
    context.bot_data["queue"] = asyncio.Queue(maxsize=5)  # kosong: job tak di antrean
    context.bot_data["ack_tokens"] = {"t-1": (CHAT_ID, ACK_MESSAGE_ID)}
    update = make_callback("t-1")

    await download_mod.cancel_ack_callback(update, context)

    assert update.callback_query.answer.await_count == 1
    assert "dilewati di titik aman" in update.callback_query.answer.await_args.args[0]


async def test_cancel_button_after_done_answers_softly(rl, settings):
    """Tombol basi (job sudah selesai) dijawab halus, BUKAN error."""
    context = make_context(rl, settings)
    update = make_callback("t-selesai")

    await download_mod.cancel_ack_callback(update, context)

    assert update.callback_query.answer.await_count == 1
    assert context.bot.delete_message.await_count == 0


async def test_cancel_button_running_job_marks_and_clears_ack(rl, settings):
    """Job yang sudah dipegang worker ditandai (bukan diklaim dihentikan)."""
    context = make_context(rl, settings)
    context.bot_data["queue"] = asyncio.Queue(maxsize=5)  # kosong: job tidak di sini
    context.bot_data["ack_tokens"] = {"t-run": (CHAT_ID, ACK_MESSAGE_ID)}
    context.bot_data["ack_messages"] = {CHAT_ID: ACK_MESSAGE_ID}
    update = make_callback("t-run")

    await download_mod.cancel_ack_callback(update, context)

    assert "t-run" in context.bot_data["ack_cancel_requested"]
    assert context.bot.delete_message.await_count == 1
    assert update.callback_query.answer.await_count == 1


async def test_second_link_replaces_ack_without_killing_second(rl, settings):
    """T-211: ack lama di-replace; job pertama TIDAK menghapus ack job kedua.

    Skenario: user mengirim link kedua selagi job pertama berjalan. Registry
    per-chat kini menunjuk ack BARU, jadi `run_job` job pertama harus menghapus
    pesan BER-token miliknya sendiri (lewat peta token), bukan ack baru itu.
    """
    context = make_context(rl, settings)
    old_token, new_token = "t-lama", "t-baru"
    old_id, new_id = 111, 222
    context.bot_data["ack_messages"] = {CHAT_ID: new_id}  # sudah di-replace
    context.bot_data["ack_tokens"] = {
        old_token: (CHAT_ID, old_id),
        new_token: (CHAT_ID, new_id),
    }
    job = Job(
        chat_id=CHAT_ID,
        user_id=1,
        url=VALID_URL,
        enqueued_at=time.monotonic(),
        context=context,
        token=old_token,  # noqa: S106 - penanda job, bukan kredensial
    )

    with (
        patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))),
        patch.object(download_mod, "send_video", AsyncMock(return_value=True)),
    ):
        await download_mod.run_job(job, context, settings)

    # Hanya ack LAMA (milik job ini) yang dihapus.
    assert context.bot.delete_message.await_args.kwargs["message_id"] == old_id
    # Registry per-chat masih menunjuk ack job kedua -> tidak tersentuh.
    assert context.bot_data["ack_messages"][CHAT_ID] == new_id
    assert new_token in context.bot_data["ack_tokens"], "token job kedua tetap hidup"


async def test_cancel_requested_skips_upload(rl, settings):
    """Job bertanda cancel melewati upload di titik aman (setelah download)."""
    context = make_context(rl, settings)
    job = _queue_acked_job(settings)
    context.bot_data["ack_cancel_requested"] = {"t-1"}
    context.bot_data["ack_messages"] = {CHAT_ID: ACK_MESSAGE_ID}
    send_video = AsyncMock(return_value=True)

    with (
        patch.object(downloader_service, "download", AsyncMock(return_value=_ok_result(settings))),
        patch.object(download_mod, "send_video", send_video),
    ):
        await download_mod.run_job(job, context, settings)

    assert send_video.await_count == 0, "video tidak dikirim untuk job dibatalkan"
    assert context.bot.delete_message.await_count == 1, "ack tetap dibersihkan"


async def test_advance_path_registers_ack_and_token(rl, settings):
    """`admit_advance_job` (jalur WP-19) juga mencatat ack + tombol Batalkan."""
    context = make_context(rl, settings)
    update = make_update(VALID_URL)
    sent = MagicMock()
    sent.message_id = ACK_MESSAGE_ID
    context.bot.send_message = AsyncMock(return_value=sent)
    queue: asyncio.Queue = asyncio.Queue(maxsize=5)
    context.bot_data["queue"] = queue
    block_workers(context.bot_data)  # cegah spawn worker nyata di jalur ini
    context.bot_data["task_counter"] = [0]
    from app.services.advance import Selection

    ok = await download_mod.admit_advance_job(
        update, context, VALID_URL, Selection(mode="video", quality=720)
    )

    assert ok is True
    assert context.bot_data["ack_messages"][CHAT_ID] == ACK_MESSAGE_ID
    queued = queue.get_nowait()
    assert queued.selection is not None and queued.selection.quality == 720
    assert queued.token in context.bot_data["ack_tokens"]
    # Teks ack tetap berisi frasa kunci WP-06 (test lama mencocokkan substring).
    text = context.bot.send_message.await_args.kwargs["text"]
    assert "Sedang memproses" in text
