"""Mekanik bantu test WP-17 (T-174): drain antrean kerja deterministik.

Satu sumber kebenaran untuk helper drain, dipakai ulang oleh `tests/conftest.py`
(re-export, untuk fixture autouse) dan oleh file test yang dulunya mem-patch
`asyncio.create_task`. Import modul ini sebagai `tests.queue_support`:
`pythonpath = ["."]` di `pyproject.toml` membuat paket namespace `tests`
bisa di-import, dan nama modulnya SAMA di kedua jalur sehingga tidak ada dua
instance kelas.

WP-17 menghapus jalur "spawn task per request" (FR-022). Test lama mengukur
"pekerjaan dijadwalkan" lewat spy `create_task`; sekarang pengukuran yang sama
dapat dari dua titik murni:

* `build_job(update, url, context)` dipanggil -> pekerjaan DIJADWALKAN
  (persis sebelum `queue.put_nowait`),
* `run_job(job, ...)` selesai -> pekerjaan DIEKSEKUSI.

`JobCollector.install()` membungkus keduanya lewat `patch.multiple`, sehingga
tiap test lama MASIH membuktikan hal yang sama (ack terkirim, `download()`
dipanggil/tidak, pesan error sampai ke chat, cleanup jalan, concurrency <= N)
tanpa melonggarkan satu pun assertion pesan.

Aturan keras WP-17: tidak ada `asyncio.sleep` untuk correctness. Sinkronisasi
memakai `asyncio.Event` (pola WP-11) atau `Queue.join()` (digerakkan
`task_done()` di worker). `sleep` kecil hanya muncul sebagai yield-perantara
saat menunggu worker yang baru di-spawn benar-benar mulai, dan tidak pernah
menjadi dasar kesimpulan test.
"""

from __future__ import annotations

import asyncio
from typing import Any

#: Batas tunggu drain. Panjang: hanya supaya test GAGAL dengan pesan jelas bila
#: job macet, bukan memberi waktu pada yang lambat.
DRAIN_SECONDS = 5.0

#: Sentinel "worker sudah diurus test": lazy-init handler jadi tidak spawn lagi.
BLOCKED_WORKERS: list[str] = ["test-owned-no-spawn"]


def queue_of(bot_data: dict[str, Any]) -> asyncio.Queue | None:
    """Antrean kerja milik `bot_data` (dibuat malas oleh handler WP-17)."""
    queue = bot_data.get("queue")
    return queue if isinstance(queue, asyncio.Queue) else None


def live_workers(bot_data: dict[str, Any]) -> list[asyncio.Task]:
    """Task worker yang masih hidup di `bot_data["workers"]`."""
    workers = bot_data.get("workers") or []
    return [t for t in workers if isinstance(t, asyncio.Task) and not t.done()]


def block_workers(bot_data: dict[str, Any]) -> None:
    """Cegah lazy-spawn worker oleh handler (test yang menguras antrean sendiri).

    Dipakai test banjir/kedaluwarsa yang butuh determinisme penuh atas
    eksekusi job. `bot_data["workers"]` sentinel membuat `_ensure_workers`
    no-op; antrean tetap dibuat handler seperti biasa.
    """
    bot_data["workers"] = list(BLOCKED_WORKERS)


def unblock_workers(bot_data: dict[str, Any]) -> None:
    """Hapus sentinel blokir (bukan membatalkan apa pun)."""
    if bot_data.get("workers") and all(w in BLOCKED_WORKERS for w in bot_data["workers"]):
        bot_data["workers"] = []


async def start_workers(
    bot_data: dict[str, Any], *, count: int | None = None
) -> list[asyncio.Task]:
    """Spawn worker `worker_loop` NYATA yang menjalankan `run_job` handler."""
    from app.handlers.download import _notify_chat, run_job
    from app.services.work_queue import ensure_workers

    bot_data["workers"] = []
    return ensure_workers(
        bot_data,
        run_job=run_job,
        notify=_notify_chat,
        settings=bot_data.get("settings"),
        count=count,
    )


async def stop_workers(bot_data: dict[str, Any]) -> list[asyncio.Task]:
    """Set `stop_event` + batalkan + `gather` semua worker (pola T-173)."""
    from app.services.work_queue import stop_workers as _stop

    unblock_workers(bot_data)
    return await _stop(bot_data)


async def drain_queue(
    bot_data: dict[str, Any],
    *,
    release: asyncio.Event | None = None,
    timeout_seconds: float = DRAIN_SECONDS,
    count: int | None = None,
) -> None:
    """Pastikan worker jalan, lepaskan gerbang, tunggu `Queue.join()`, tutup.

    Urutan deterministik: spawn worker bila belum ada -> `release.set()` (job
    yang menahan `asyncio.Event` melanjutkan) -> `queue.join()` (kembali hanya
    setelah `task_done()` terakhir) -> batalkan + reap worker, jadi tidak ada
    "Task was destroyed but it is pending" di akhir test.
    """
    queue = queue_of(bot_data)
    if queue is None:
        return
    unblock_workers(bot_data)
    if not live_workers(bot_data):
        await start_workers(bot_data, count=count)
    try:
        if release is not None:
            release.set()
        async with asyncio.timeout(timeout_seconds):
            await queue.join()
    finally:
        await stop_workers(bot_data)


class JobCollector:
    """Rekam "pekerjaan dijadwalkan" + "pekerjaan dieksekusi" lewat antrean.

    Pengganti mekanik spy `create_task` (WP-06..WP-16). API-nya dibuat mirip
    pemakai lama supaya adaptasi test bersifat satu-ganti-per-baris:

    * `collector.jobs`   <- pekerjaan yang diterima antrean (dulu `.tasks`)
    * `collector.done`   <- pekerjaan yang selesai dieksekusi worker
    * `collector.rejected` <- pekerjaan yang DITOLAK admission (queue penuh)
    * `collector.install()` -> context manager patch (nama tetap)
    * `collector.drain()`   -> tunggu semua selesai (nama + makna tetap)
    * `collector.calls`     -> `Mock.call_args_list`-style, untuk assertion lama
      `mock_task.call_args.args[0]` dst. cukup diganti `collector.calls[...]`
    """

    def __init__(
        self, *, timeout_seconds: float = DRAIN_SECONDS, worker_count: int | None = None
    ) -> None:
        self.jobs: list[Any] = []
        self.done: list[Any] = []
        self.rejected: list[Any] = []
        self.calls: list[tuple[Any, str]] = []
        self.timeout_seconds = timeout_seconds
        self.worker_count = worker_count
        self._patches: list[Any] = []

    # ---------------------------------------------------------- patching --
    def install(self) -> JobCollector:
        """Patch `build_job` + `run_job` di modul handler (dipakai sebagai CM)."""
        from unittest.mock import patch

        from app.handlers import download as download_mod

        real_build = download_mod.build_job
        real_run = download_mod.run_job

        def build_spy(update, url, context):
            self.calls.append((update, url))
            job = real_build(update, url, context)
            self.jobs.append(job)
            return job

        async def run_spy(job, *args, **kwargs):
            try:
                return await real_run(job, *args, **kwargs)
            finally:
                self.done.append(job)

        self._patches = [
            patch.object(download_mod, "build_job", build_spy),
            patch.object(download_mod, "run_job", run_spy),
        ]
        for p in self._patches:
            p.start()
        return self

    def uninstall(self) -> None:
        for p in self._patches:
            p.stop()
        self._patches = []

    def __enter__(self) -> JobCollector:
        if not self._patches:
            self.install()
        return self

    def __exit__(self, *exc_info) -> None:
        self.uninstall()

    # ------------------------------------------------------- observasi ---
    @property
    def scheduled(self) -> int:
        """Banyaknya pekerjaan yang masuk antrean (bukti 'dijadwalkan')."""
        return len(self.jobs)

    def bot_data_with_queues(self) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        for job in self.jobs:
            bot_data = getattr(job, "context", None)
            bot_data = getattr(bot_data, "bot_data", None)
            if isinstance(bot_data, dict) and bot_data not in seen:
                seen.append(bot_data)
        return seen

    # ------------------------------------------------------------- drain --
    async def drain(self) -> None:
        """Tunggu semua pekerjaan yang direkam selesai (via `Queue.join()`)."""
        for bot_data in self.bot_data_with_queues():
            await drain_queue(
                bot_data, count=self.worker_count, timeout_seconds=self.timeout_seconds
            )

    def close_pending(self) -> None:
        """Buang job yang masih tertahan di antrean tanpa mengeksekusinya.

        Padanan `.close()` pada coroutine task lama: dipakai test yang hanya
        ingin membuktikan "pekerjaan dijadwalkan" lalu berhenti (rate limiter,
        jalur stats counter). Worker di-block lebih dulu lewat
        `block_workers(bot_data)` agar tidak ada yang sempat mengambil job.

        Reset rekaman spy karena test berikutnya akan memasang collector baru
        di blok kedua dan mengharapkan `scheduled == 0`.
        """
        for bot_data in self.bot_data_with_queues():
            queue = queue_of(bot_data)
            if queue is None:
                continue
            block_workers(bot_data)
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    queue.task_done()
        # Bersihkan rekaman spy setelah drain agar counter collector baru 0.
        self.jobs.clear()
