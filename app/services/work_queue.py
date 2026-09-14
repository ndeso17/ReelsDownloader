"""Antrean kerja in-process + admission control (WP-17, FR-022, anti-OOM).

Murni in-process: satu `asyncio.Queue` terbatas + segelintir task worker tetap
jumlah. Tidak ada Redis, tidak ada database, tidak ada proses eksternal, tidak
ada dependency baru (PRD Section 6).

Alasan desain (PLAN WP-17, baris 1678):

1. `get_nowait()` + `asyncio.sleep(0.01)`, BUKAN `Queue.get()` yang dibungkus
   `asyncio.wait_for`/`asyncio.timeout`. `wait_for` membatalkan coroutine `get`
   saat timeout dan item yang sudah terambil ikut hilang = job user lenyap
   tanpa pernah diproses. Polling eksplisit membuat pengambilan item dan
   pembatalan tidak pernah terjadi di titik yang sama.
2. `Queue.shutdown()` sengaja TIDAK dipakai: tidak ada di Python 3.12.3
   (dibaca lewat `inspect`, lihat Log WP-17). Shutdown memakai `stop_event` +
   `Task.cancel()` + `asyncio.gather(..., return_exceptions=True)`.
3. Admission control terjadi SEBELUM ada objek kerja baru: `put_nowait()` pada
   queue ber-`maxsize` menandakan penuh lewat `QueueFull`, jadi permintaan ke-N
   ditolak tanpa alokasi task. Jumlah task per request = nol konstan, itulah
   bukti anti-OOM (FR-022).

Urutan lapis di handler tidak boleh bertukar: gate akses -> validasi URL ->
rate limiter -> antrean (FR-011 sebelum FR-022).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "MSG_QUEUE_EXPIRED",
    "MSG_QUEUE_FULL",
    "Job",
    "build_job",
    "ensure_workers",
    "stop_workers",
    "worker_loop",
]

#: Literal PRD Section 6 / FR-022 (tanpa placeholder `[pilihan]`).
MSG_QUEUE_FULL = "🚦 Server sedang penuh, coba lagi sebentar."
MSG_QUEUE_EXPIRED = "⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya."

#: Jeda polling antrean. Hanya menunda pengambilan item, BUKAN penjaga
#: kebenaran: `join()`/`task_done()` yang menentukan selesai-tidaknya.
POLL_INTERVAL_SECONDS = 0.01

#: Fallback bila `Settings` tidak membawa field (mis. `model_construct()` test lama).
_DEFAULT_MAX_WAIT_SECONDS = Settings.model_fields["max_queue_wait_seconds"].default


@dataclass(frozen=True)
class Job:
    """Satu unit kerja: satu URL dari satu chat, siap dieksekusi worker."""

    chat_id: int
    user_id: int | None
    url: str
    enqueued_at: float
    context: Any = field(repr=False)


def build_job(update: Any, url: str, context: Any) -> Job:
    """Susun `Job` dari `update` Telegram + URL yang sudah tervalidasi.

    `enqueued_at` memakai `time.monotonic()` (bukan jam dinding) supaya cek
    kedaluwarsa tahan terhadap lompatan/NTP koreksi jam sistem.
    """
    effective_chat = getattr(update, "effective_chat", None)
    chat_id = getattr(effective_chat, "id", 0)
    effective_user = getattr(update, "effective_user", None)
    user_id = getattr(effective_user, "id", None) if effective_user is not None else None
    return Job(
        chat_id=chat_id,
        user_id=user_id,
        url=url,
        enqueued_at=time.monotonic(),
        context=context,
    )


def max_wait_seconds_for(job: Job) -> float:
    """Ambang kedaluwarsa antrean untuk `job` (detik), dari settings konteks."""
    settings = _settings_of(job)
    value = getattr(settings, "max_queue_wait_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(_DEFAULT_MAX_WAIT_SECONDS)
    return float(value)


def _settings_of(job: Job) -> Any:
    bot_data = getattr(job.context, "bot_data", None)
    if not isinstance(bot_data, dict):
        return None
    return bot_data.get("settings")


def is_expired(job: Job, now: float | None = None) -> bool:
    """True bila `job` menunggu di antrean melebihi `MAX_QUEUE_WAIT_SECONDS`."""
    if now is None:
        now = time.monotonic()
    return (now - job.enqueued_at) > max_wait_seconds_for(job)


async def worker_loop(
    queue: asyncio.Queue[Job],
    stop_event: asyncio.Event,
    run_job: Callable[[Job], Coroutine[Any, Any, Any]],
    notify: Callable[[Job, str], Coroutine[Any, Any, Any]],
    cleanup: Callable[[Job], None] | None = None,
) -> None:
    """Konsumsi `queue` FIFO sampai `stop_event` diset.

    `run_job(job)` membalik apa pun (worker tidak bergantung nilai baliknya);
    `notify(job, text)` dipakai untuk pesan kedaluwarsa. `cleanup(job)` opsional
    dipakai pada jalur job dibuang TANPA `run_job` dijalankan (kedaluwarsa) agar
    penanda 'slot ditahan' dari sisi handler (task counter WP-17) tetap dilepas.
    Setiap cabang dijamin memanggil `queue.task_done()` tepat satu kali,
    termasuk saat job dilempar keluar sebagai exception, supaya `join()` tidak
    pernah menggantung.
    """
    while not stop_event.is_set():
        try:
            job = queue.get_nowait()
        except asyncio.QueueEmpty:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        try:
            if is_expired(job):
                waited = time.monotonic() - job.enqueued_at
                logger.warning(
                    "job kedaluwarsa di antrean (chat %s, %.1fs): %s",
                    job.chat_id,
                    waited,
                    job.url,
                )
                await _notify_quietly(notify, job, MSG_QUEUE_EXPIRED)
                if cleanup is not None:
                    try:
                        cleanup(job)
                    except Exception:
                        logger.warning("cleanup job kedaluwarsa gagal", exc_info=True)
                continue
            await run_job(job)
        except Exception:
            # Worker tidak pernah mati diam-diam: catat penuh, lanjut job berikut.
            logger.exception("worker_loop: job gagal tak terduga, lanjut antrean")
        finally:
            queue.task_done()


async def _notify_quietly(
    notify: Callable[[Job, str], Coroutine[Any, Any, Any]],
    job: Job,
    text: str,
) -> None:
    """Kirim `text` ke chat `job`; kegagalan kirim tidak boleh menghentikan worker."""
    try:
        await notify(job, text)
    except Exception:
        logger.warning("notify user gagal (chat %s)", job.chat_id, exc_info=True)


async def _noop_notify(job: Job, text: str) -> None:
    """Notifikasi tanpa saluran (dipakai saat `context.bot` tidak tersedia)."""
    logger.info("antrean: chat %s: %s", job.chat_id, text)


def ensure_workers(
    bot_data: dict[str, Any],
    *,
    run_job: Callable[[Job], Coroutine[Any, Any, Any]],
    queue: asyncio.Queue[Job] | None = None,
    settings: Any = None,
    notify: Callable[[Job, str], Coroutine[Any, Any, Any]] | None = None,
    cleanup: Callable[[Job], None] | None = None,
    count: int | None = None,
    name_prefix: str = "download-worker",
) -> list[asyncio.Task]:
    """Spawn worker `worker_loop` idempoten; simpan di `bot_data["workers"]`.

    Jumlah worker = `max_concurrent_downloads` (dua knob beda dengan
    `queue_max_size`; tidak boleh disamakan). Bila `bot_data["workers"]` sudah
    terisi, fungsi ini hanya mengembalikan daftar itu tanpa spawn kedua.
    """
    existing = bot_data.get("workers")
    if existing:
        return list(existing)

    target_queue = queue if queue is not None else bot_data.get("queue")
    if target_queue is None:
        raise RuntimeError("ensure_workers: tidak ada queue di bot_data")
    stop_event = bot_data.get("stop_event")
    if stop_event is None:
        stop_event = asyncio.Event()
        bot_data["stop_event"] = stop_event

    if count is None:
        resolved = settings if settings is not None else bot_data.get("settings")
        value = getattr(resolved, "max_concurrent_downloads", None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            value = int(Settings.model_fields["max_concurrent_downloads"].default)
        count = value

    callback = notify if notify is not None else _noop_notify
    workers: list[asyncio.Task] = []
    for _index in range(count):
        task = asyncio.create_task(
            worker_loop(target_queue, stop_event, run_job, callback, cleanup),
        )
        workers.append(task)
    bot_data["workers"] = workers
    bot_data["queue"] = target_queue
    logger.info("worker antrean aktif: %d task, maxsize=%s", count, target_queue.maxsize)
    return workers


async def stop_workers(bot_data: dict[str, Any]) -> list[asyncio.Task]:
    """Set `stop_event`, batalkan, lalu `gather(return_exceptions=True)`.

    Membalik daftar task yang sudah dibatalkan (sudah direap, jadi tidak ada
    "Task was destroyed but it is pending" di akhir run).
    """
    stop_event = bot_data.get("stop_event")
    if isinstance(stop_event, asyncio.Event):
        stop_event.set()
    workers = list(bot_data.get("workers") or [])
    for task in workers:
        task.cancel()
    if workers:
        async with asyncio.timeout(5.0):
            await asyncio.gather(*workers, return_exceptions=True)
    bot_data["workers"] = []
    return workers
