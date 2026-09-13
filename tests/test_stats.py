"""Test WP-16 (T-167): stats pemakaian + notifikasi admin realtime (FR-021, SC 17, 18).

Pola test sama WP-15 (`tests/test_access.py`): `update`/`context`/`bot` adalah
MagicMock/AsyncMock, tanpa network, tanpa panggilan Telegram nyata (AGENTS.md §4.6).
Semua token di file ini string dummy pendek (AGENTS.md §5a).

`/start` menjadwalkan `asyncio.create_task(..., name="stats-notify-flush")` sebagai
fire-and-forget (notifikasi admin + flush atomik `stats.json`). Test menunggu tugas
latar itu lewat `drain_pending_stats()` yang `asyncio.wait` task BERNAMA tersebut:
bukan `asyncio.sleep` arbitrer, jadi tidak ada race antara tulis atomik dan assert.
WP-16 tidak punya loop periodik (flush hanya saat user baru + saat shutdown), jadi
tidak ada task yang menyeberang antar test; `drain` tetap membatalkan + meng-reap
sisa task di `finally` sebagai pengaman.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import stat
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from telegram.error import RetryAfter, TelegramError

from app.config import Settings
from app.handlers import account as account_mod
from app.handlers import download as download_mod
from app.handlers import start as start_mod
from app.handlers.account import stats as stats_command
from app.handlers.download import download_handler
from app.handlers.start import start
from app.services import downloader as downloader_service
from app.services.access import MSG_ACCESS_DENIED
from app.services.downloader import DownloadResult
from app.services.errors import DownloadFailedError, UploadError
from app.services.rate_limiter import UserRateLimiter
from app.services.stats import (
    MSG_NEW_USER_ADMIN,
    Stats,
    build_new_user_message,
    notify_new_user,
)

DUMMY_TOKEN = SecretStr(" ".join(["dummy", "token"]))  # bukan kredensial nyata
VALID_URL = "https://www.instagram.com/reel/xxxxx/"
UNSUPPORTED_URL = "https://example.com/nope"

#: Nama task fire-and-forget yang dibuat `app/handlers/start.py` (kontrak test).
BG_TASK_NAME = "stats-notify-flush"

OWNER_ID = 111
ADMIN_CHAT = 777
NOTIF_MARKER = "User baru memakai bot"
#: Batas tunggu task latar. Panjang: hanya dipakai supaya test GAGAL dengan pesan
#: jelas bila task macet, bukan untuk memberi waktu bagi yang lambat.
DRAIN_TIMEOUT = 5.0


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings sah (lewat validator penuh) dengan path sementara terisolasi."""
    download_dir = tmp_path / "dl"
    download_dir.mkdir(exist_ok=True)
    base = {
        "telegram_bot_token": DUMMY_TOKEN,
        "download_dir": str(download_dir),
        "users_file": str(tmp_path / "users.json"),
        "stats_file": str(tmp_path / "stats.json"),
        "owner_user_id": OWNER_ID,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def make_update(text: str = "/start", user_id: int | None = 999) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123456
    if user_id is None:
        update.effective_user = None
    else:
        update.effective_user = MagicMock()
        update.effective_user.id = user_id
        update.effective_user.first_name = "Budi"
        update.effective_user.username = "budi_utama"
    return update


def make_context(settings: Settings, stats: Stats | None = None, **extra) -> MagicMock:
    context = MagicMock()
    bot_data: dict = {"rate_limiter": UserRateLimiter(10), "settings": settings}
    if stats is not None:
        bot_data["stats"] = stats
    bot_data.update(extra)
    context.bot_data = bot_data
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []
    return context


def notification_texts(context: MagicMock) -> list[str]:
    """Hanya teks `send_message` berupa notifikasi user baru (bukan welcome/menu)."""
    return [t for t in _sent_texts(context) if NOTIF_MARKER in t]


def _sent_texts(context: MagicMock) -> list[str]:
    return [call.kwargs.get("text") or "" for call in context.bot.send_message.await_args_list]


def _drain_targets(loop: asyncio.AbstractEventLoop) -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks(loop) if t.get_name() == BG_TASK_NAME]


def _assert_stats_written(path: Path) -> None:
    """Helper sinkron: assert I/O tidak inline di coroutine (ruff ASYNC240, pola
    `tests/test_concurrency.py::_assert_only_file`)."""
    import os

    assert os.path.exists(str(path)), f"stats belum tertulis: {path}"


async def drain_pending_stats() -> None:
    """Tunggu seluruh task `stats-notify-flush` selesai, lalu re-raise kegagalannya.

    Dipakai SEBELUM assert efek samping fire-and-forget (notifikasi terkirim,
    `stats.json` tertulis). Tanpa `asyncio.sleep` arbitrer: `asyncio.wait` blok
    sampai task benar-benar selesai; kegagalan task tetap terdeteksi lewat
    `task.exception()`. Sisa task dibatalkan + di-reap di `finally` supaya tidak
    ada task menggantung yang menyeberang antar test.
    """
    loop = asyncio.get_running_loop()
    failures: list[BaseException] = []
    try:
        pending = _drain_targets(loop)
        if pending:
            done, still = await asyncio.wait(pending, timeout=DRAIN_TIMEOUT)
            for _task in sorted(done, key=id):
                if _task.cancelled():
                    continue
                exc = _task.exception()
                if exc is not None:
                    failures.append(exc)
            for _task in still:
                failures.append(
                    AssertionError(f"task {_task} tidak selesai dalam {DRAIN_TIMEOUT}s")
                )
    finally:
        leftovers = _drain_targets(loop)
        for task in leftovers:
            task.cancel()
        if leftovers:
            await asyncio.gather(*leftovers, return_exceptions=True)
    if failures:
        raise failures[0]


def _leftover_tmp(directory: str | Path) -> list[str]:
    return sorted(n for n in os.listdir(directory) if n.endswith(".tmp"))


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------- (a) user baru: record_user True + TEPAT SATU notifikasi ----------------


async def test_start_new_user_sends_exactly_one_admin_notification(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats = Stats()
    context = make_context(settings, stats=stats)

    await start(make_update("/start", user_id=999), context)
    await drain_pending_stats()

    texts = notification_texts(context)
    assert len(texts) == 1, f"harus tepat SATU notifikasi, dapat {len(texts)}"
    body = texts[0]

    # Regex per baris (PLAN T-167 butir a): total, ID, Nama, Username.
    assert re.search(r"(?m)^🆕 User baru memakai bot$", body)
    assert re.search(r"(?m)^ID: 999$", body)
    assert re.search(r"(?m)^Nama: Budi$", body)
    assert re.search(r"(?m)^Username: @budi_utama$", body)
    assert re.search(r"(?m)^Total user: 1$", body)

    # Target chat = ADMIN_NOTIFY_CHAT_ID (PRD FR-021).
    notify_call = next(
        call
        for call in context.bot.send_message.await_args_list
        if NOTIF_MARKER in (call.kwargs.get("text") or "")
    )
    assert notify_call.kwargs["chat_id"] == ADMIN_CHAT
    assert stats.total_users == 1


# ---------------- (b) user sama kedua kali: False + nol notifikasi ulang ----------------


async def test_repeat_start_same_user_sends_no_further_notification(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    context = make_context(settings, stats=Stats())

    await start(make_update("/start", user_id=999), context)
    await drain_pending_stats()
    assert len(notification_texts(context)) == 1

    context.bot.send_message.reset_mock()
    await start(make_update("/start", user_id=999), context)
    await drain_pending_stats()
    assert notification_texts(context) == [], "SC 17: satu notifikasi per user seumur hidup"
    assert context.bot_data["stats"].total_users == 1


# ---------------- (c) 3 ID berbeda: tiga notifikasi bercount 1, 2, 3 ----------------


async def test_three_distinct_users_produce_notifications_counted_1_2_3(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats = Stats()
    context = make_context(settings, stats=stats)

    totals: list[int] = []
    chat_ids: list[int] = []
    seen_calls = 0
    for user_id in (10, 20, 30):
        await start(make_update("/start", user_id=user_id), context)
        await drain_pending_stats()
        calls = context.bot.send_message.await_args_list
        for call in calls[seen_calls:]:  # hanya panggilan RONDE ini, tidak dihitung ulang
            text = call.kwargs.get("text") or ""
            if NOTIF_MARKER not in text:
                continue
            match = re.search(r"(?m)^Total user: (\d+)$", text)
            assert match, f"notifikasi tanpa baris 'Total user': {text!r}"
            totals.append(int(match.group(1)))
            chat_ids.append(call.kwargs["chat_id"])
            assert f"ID: {user_id}" in text
        seen_calls = len(calls)
    assert totals == [1, 2, 3]
    assert chat_ids == [ADMIN_CHAT, ADMIN_CHAT, ADMIN_CHAT]
    assert stats.total_users == 3


# ---------------- (d) admin chat kosong: nol send_message, nol exception, INFO log -------


async def test_notify_new_user_without_admin_chat_only_logs_info(tmp_path, caplog):
    # `bot_mode=public` mengizinkan `owner_user_id=None`; `admin_chat_id` ikut None.
    settings = make_settings(
        tmp_path, bot_mode="public", admin_notify_chat_id=None, owner_user_id=None
    )
    assert settings.admin_chat_id is None

    sent = AsyncMock()
    bot = MagicMock()
    bot.send_message = sent

    with caplog.at_level("INFO", logger="app.services.stats"):
        await notify_new_user(bot, settings, MSG_NEW_USER_ADMIN)  # tidak raise
    assert sent.await_count == 0
    assert "admin chat tidak diset" in caplog.text

    # Jalur handler: `/start` tetap menjawab user tanpa admin yang dikonfigurasi.
    stats = Stats()
    context = make_context(settings, stats=stats)
    update = make_update("/start", user_id=4242)
    await start(update, context)
    await drain_pending_stats()
    assert update.message.reply_text.call_args.args[0].startswith("👋")
    assert notification_texts(context) == []
    assert stats.total_users == 1


# ---------------- (e) kegagalan kirim tidak propagate, counter tetap naik ----------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(RetryAfter(2), id="RetryAfter"),
        pytest.param(TelegramError("Forbidden: bot was blocked by the user"), id="TelegramError"),
        pytest.param(OSError("network down"), id="NetworkError"),
    ],
)
async def test_send_message_failure_does_not_propagate_counter_still_rises(tmp_path, exc):
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats = Stats()
    context = make_context(settings, stats=stats)

    async def flaky_send(**kwargs):
        if NOTIF_MARKER in (kwargs.get("text") or ""):
            raise exc
        return MagicMock()

    context.bot.send_message = flaky_send

    # `/start` sendiri tidak boleh raise (notifikasi fire-and-forget).
    await start(make_update("/start", user_id=1234), context)
    # `notify_new_user` menelan exception, jadi task latar selesai tanpa kegagalan.
    await drain_pending_stats()

    assert stats.total_users == 1, "counter tetap bertambah meski notifikasi gagal"
    assert stats.record_user(5678) is True
    assert stats.total_users == 2


async def test_notify_new_user_swallows_exception_and_logs_warning(caplog):
    """Unit `notify_new_user`: exception tertelan, hanya WARNING (kontrak PLAN T-162)."""

    async def boom(**kwargs):
        raise RetryAfter(2)

    bot = MagicMock()
    bot.send_message = boom
    settings = Settings.model_construct(admin_notify_chat_id=ADMIN_CHAT, owner_user_id=None)
    with caplog.at_level("WARNING", logger="app.services.stats"):
        await notify_new_user(bot, settings, "teks uji")
    assert "notifikasi admin gagal" in caplog.text


# ---------------- (f) round-trip stats.json: atomik, 0600, tanpa tmp, os.replace ---------


async def test_roundtrip_survives_restart(tmp_path):
    """Skenario restart: proses baru memuat `first_seen` dari berkas hasil flush `/start`."""
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats_path = Path(settings.stats_file)

    # --- run pertama: dua user baru lewat `/start` (flush terjadi di task latar) ---
    first_run = Stats()
    context = make_context(settings, stats=first_run)
    await start(make_update("/start", user_id=101), context)
    await drain_pending_stats()  # tunggu task flush SEBELUM assert, tanpa sleep
    await start(make_update("/start", user_id=202), context)
    await drain_pending_stats()

    assert first_run.total_users == 2
    _assert_stats_written(stats_path)
    on_disk = _read_json(stats_path)
    assert sorted(on_disk["first_seen"]) == ["101", "202"]
    assert on_disk["total_users"] == 2

    # --- run kedua: objek baru, muat dari disk (pola `Stats.load_or_new` main.py) ---
    revived = Stats.load_or_new(stats_path)
    assert revived.total_users == 2
    assert revived.record_user(101) is False, "user lama tidak boleh dihitung ulang"
    assert revived.record_user(303) is True
    assert revived.total_users == 3

    # --- flush shutdown (T-166) menutup siklus tanpa task latar ---
    assert revived.save(stats_path) is True
    assert Stats.load_or_new(stats_path).total_users == 3
    assert _leftover_tmp(tmp_path) == []


def test_save_then_read_is_identical_and_atomic(tmp_path):
    stats_path = tmp_path / "stats.json"
    stats = Stats()
    stats.record_user(101)
    stats.record_user(202)
    stats.inc_processed()
    stats.inc_rejected("rate_limited")
    stats.inc_rejected("unsupported_url")
    stats.inc_rejected("unsupported_url")

    assert stats.save(stats_path) is True
    # Berkas == snapshot (kolom persist dibaca balik identik).
    assert _read_json(stats_path) == stats.snapshot()

    # Mode 0600 (PRD FR-021 Privasi) + tidak ada `*.tmp` yatim.
    assert stat.S_IMODE(os.stat(stats_path).st_mode) == 0o600
    assert _leftover_tmp(tmp_path) == []

    reloaded = Stats()
    reloaded.load(stats_path)
    assert reloaded.first_seen == stats.first_seen
    assert reloaded.total_users == 2


def test_save_uses_os_replace(tmp_path):
    target = tmp_path / "stats.json"
    stats = Stats()
    stats.record_user(42)
    real_replace = os.replace
    seen: list[tuple[str, str]] = []

    def spy(src, dst, *args, **kwargs):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst, *args, **kwargs)

    with patch("os.replace", side_effect=spy):
        assert stats.save(target) is True

    assert len(seen) == 1, "satu replace atomik"
    src, dst = seen[0]
    assert dst == str(target)
    assert src != str(target) and src.endswith(".tmp")
    assert _leftover_tmp(tmp_path) == []


def test_load_missing_or_corrupt_starts_from_zero_without_raise(tmp_path, caplog):
    missing = tmp_path / "absent.json"
    stats = Stats()
    with caplog.at_level("WARNING", logger="app.services.stats"):
        stats.load(missing)
    assert stats.total_users == 0
    assert any("tidak ada" in record.getMessage() for record in caplog.records)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{bukan json", encoding="utf-8")
    stats2 = Stats()
    stats2.load(corrupt)
    assert stats2.snapshot() == {
        "total_users": 0,
        "processed": 0,
        "rejected": 0,
        "rejected_reasons": {},
        "first_seen": {},
    }

    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2, 3]", encoding="utf-8")
    stats3 = Stats()
    stats3.load(not_object)
    assert stats3.total_users == 0


def test_save_failure_logs_error_and_returns_false(tmp_path, caplog):
    # Parent belum ada -> mkstemp OSError; kontrak: `False` + log, TANPA raise.
    target = tmp_path / "belum" / "dibuat" / "stats.json"
    stats = Stats()
    stats.record_user(1)
    with caplog.at_level("ERROR", logger="app.services.stats"):
        assert stats.save(target) is False
    assert "gagal menyimpan stats file" in caplog.text
    assert stats.total_users == 1, "state in-memory tetap benar walau disk gagal"
    assert _leftover_tmp(tmp_path) == []


def test_stats_save_is_race_safe_unique_tmp_names(tmp_path):
    """Pola WP-15 REWORK-R1: banyak penulis serentak tidak pernah berbagi berkas tmp."""
    target = tmp_path / "stats.json"
    Stats().save(target)
    real_replace = os.replace
    sources: list[str] = []
    barrier = threading.Barrier(6)

    def spy(src, dst, *args, **kwargs):
        sources.append(str(src))
        return real_replace(src, dst, *args, **kwargs)

    def writer(seed: int) -> None:
        stats = Stats()
        for offset in range(5):
            stats.record_user(seed * 1000 + offset)
        barrier.wait()  # semua penulis tekan titik tulis sekaligus
        stats.save(target)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    with patch("os.replace", side_effect=spy):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(sources) == len(set(sources)) == 6, "nama tmp wajib unik per penulisan"
    assert _leftover_tmp(tmp_path) == []
    # Berkas final tetap JSON valid (tidak ada interleave) dengan struktur lengkap.
    data = _read_json(target)
    assert set(data) == {
        "total_users",
        "processed",
        "rejected",
        "rejected_reasons",
        "first_seen",
    }
    assert data["total_users"] == len(data["first_seen"])


# ---------------- (g) `/stats`: owner melihat angka, non-owner ditolak ----------------


async def test_stats_owner_shows_four_numbers_and_reason_detail(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=OWNER_ID)
    stats = Stats()
    for user_id in (1, 2, 3):
        stats.record_user(user_id)
    stats.inc_processed()
    stats.inc_processed()
    stats.inc_rejected("rate_limited")
    stats.inc_rejected("access_denied")
    context = make_context(settings, stats=stats)

    update = make_update("/stats", user_id=OWNER_ID)
    await stats_command(update, context)
    body = update.message.reply_text.call_args.args[0]

    assert body.splitlines()[0] == "📊 Statistik pemakaian"
    # 4 angka wajib SC 18: user unik, diproses, ditolak, antrean (+rincian reason).
    assert re.search(r"(?m)^User unik: 3$", body)
    assert re.search(r"(?m)^Diproses \(sejak restart\): 2$", body)
    assert re.search(r"(?m)^Ditolak \(sejak restart\): 2$", body)
    assert re.search(r"(?m)^Rincian ditolak: access_denied=1, rate_limited=1$", body)
    # Fallback PLAN T-165: WP-17 belum jalan (tanpa kunci `queue` di bot_data).
    assert re.search(r"(?m)^Antrean: n/a \(belum diwiring\)$", body)


async def test_stats_uses_queue_qsize_when_wired(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=OWNER_ID)
    queue = MagicMock()
    queue.qsize.return_value = 5
    context = make_context(settings, stats=Stats(), queue=queue)

    update = make_update("/stats", user_id=OWNER_ID)
    await stats_command(update, context)
    body = update.message.reply_text.call_args.args[0]
    assert re.search(rf"(?m)^Antrean: 5/{settings.queue_max_size}$", body)
    queue.qsize.assert_called_once()


async def test_stats_non_owner_is_denied_without_leaking_numbers(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=OWNER_ID)
    stats = Stats()
    stats.record_user(999)
    context = make_context(settings, stats=stats)

    update = make_update("/stats", user_id=999)
    await stats_command(update, context)
    reply = update.message.reply_text.call_args.args[0]
    assert reply == MSG_ACCESS_DENIED
    assert "User unik" not in reply, "angka/daftar tidak dibocorkan ke non-admin"


async def test_stats_is_owner_only_even_in_public_mode(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", owner_user_id=OWNER_ID)
    stats = Stats()
    stats.record_user(1)
    context = make_context(settings, stats=stats)

    stranger = make_update("/stats", user_id=4242)
    await stats_command(stranger, context)
    assert stranger.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED

    owner = make_update("/stats", user_id=OWNER_ID)
    await stats_command(owner, context)
    assert "User unik: 1" in owner.message.reply_text.call_args.args[0]


async def test_stats_without_user_is_denied(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", owner_user_id=OWNER_ID)
    context = make_context(settings, stats=Stats())
    update = make_update("/stats", user_id=None)
    await stats_command(update, context)
    assert update.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED


# ---------------- (h) unit: akuntansi per reason + snapshot siap-JSON ----------------


def test_inc_rejected_accounts_per_reason_and_snapshot_is_json_safe():
    stats = Stats()
    stats.record_user(1)
    stats.inc_rejected("rate_limited")
    stats.inc_rejected("access_denied")
    stats.inc_rejected("rate_limited")
    stats.inc_processed()

    snap = stats.snapshot()
    assert snap["rejected"] == 3
    assert snap["rejected_reasons"] == {"rate_limited": 2, "access_denied": 1}
    assert snap["processed"] == 1
    assert snap["total_users"] == 1

    # Snapshot = salinan; mutasi hasilnya tidak merusak state internal.
    snap["first_seen"]["999"] = "suntik"
    snap["rejected_reasons"]["rate_limited"] = 999
    assert "999" not in stats.first_seen
    assert stats.rejected_reasons["rate_limited"] == 2

    json.dumps(snap)  # serializable tanpa custom encoder


def test_record_user_counts_unique_only_and_rejects_bad_ids():
    stats = Stats()
    assert stats.record_user(7) is True, "kemunculan pertama"
    assert stats.record_user("7") is False, "kunci = int: '7' dan 7 adalah user yang sama"
    assert stats.record_user(7) is False
    assert stats.record_user("bukan angka") is False
    assert stats.record_user(None) is False
    assert stats.total_users == 1
    assert list(stats.first_seen) == ["7"]


def test_loaded_run_resets_since_restart_counters(tmp_path):
    """Keputusan Executor (Log WP-16): processed/rejected sejak-restart, nol di awal."""
    path = tmp_path / "stats.json"
    stats = Stats()
    stats.record_user(1)
    stats.inc_processed()
    stats.inc_rejected("rate_limited")
    assert stats.save(path) is True
    assert _read_json(path)["processed"] == 1, "jejak run terakhir tetap tertulis"

    revived = Stats.load_or_new(path)
    assert revived.processed == 0
    assert revived.rejected == 0
    assert revived.rejected_reasons == {}
    assert revived.total_users == 1


# ---------------- pola pesan notifikasi (T-162) ----------------


def test_build_new_user_message_matches_plan_pattern_line_by_line():
    user = MagicMock()
    user.id = 1234
    user.first_name = "Budi"
    user.username = "budi_utama"
    message = build_new_user_message(user, total=7)
    assert message == MSG_NEW_USER_ADMIN.format(
        user_id=1234, first_name="Budi", username="budi_utama", total=7
    )
    assert message.splitlines() == [
        "🆕 User baru memakai bot",
        "ID: 1234",
        "Nama: Budi",
        "Username: @budi_utama",
        "Total user: 7",
    ]


def test_build_new_user_message_uses_dash_for_missing_identity():
    user = MagicMock()
    user.id = 42
    user.first_name = None
    user.username = None
    assert build_new_user_message(user, total=1).splitlines() == [
        "🆕 User baru memakai bot",
        "ID: 42",
        "Nama: -",
        "Username: @-",
        "Total user: 1",
    ]


# ---------------- jalur test lama: tanpa stats di bot_data (T-163/T-164) ----------------


async def test_start_without_stats_key_still_answers_welcome(tmp_path):
    """`bot_data.get('stats')` boleh None (test WP-06/08/09/10): skip pencatatan."""
    settings = make_settings(tmp_path, bot_mode="public")
    context = make_context(settings, stats=None)
    update = make_update("/start", user_id=999)

    await start(update, context)
    await drain_pending_stats()

    assert update.message.reply_text.call_args.args[0].startswith("👋 Instagram")
    assert notification_texts(context) == []


async def test_start_with_no_effective_user_skips_recording(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats = Stats()
    context = make_context(settings, stats=stats)
    update = make_update("/start", user_id=None)

    await start(update, context)
    await drain_pending_stats()

    assert stats.total_users == 0
    assert notification_texts(context) == []


# ---------------- NFR Performance: /start tidak menunggu notifikasi (T-163) -------------


async def test_start_replies_before_notification_completes(tmp_path):
    """Welcome+menu dibalas SEBELUM jaringan notifikasi selesai (ack < 2 dtk)."""
    settings = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    stats = Stats()
    context = make_context(settings, stats=stats)

    gate = asyncio.Event()
    menu_sent: list[str] = []

    async def slow_send(**kwargs):
        text = kwargs.get("text") or ""
        if NOTIF_MARKER in text:
            await gate.wait()
        else:
            menu_sent.append(text)
        return MagicMock()

    context.bot.send_message = slow_send
    update = make_update("/start", user_id=999)

    await start(update, context)  # harus return tanpa menunggu `gate`
    assert update.message.reply_text.await_count == 1
    assert menu_sent, "blok menu sudah terkirim sebelum notifikasi selesai"

    loop = asyncio.get_running_loop()
    pending = _drain_targets(loop)
    assert pending and not pending[0].done(), "notifikasi masih berjalan di latar"
    gate.set()
    await drain_pending_stats()


# ---------------- T-164: pencatatan di `download_handler` ----------------


def _download_context(tmp_path, *, bot_mode="private", users=None):
    settings = make_settings(tmp_path, bot_mode=bot_mode, owner_user_id=OWNER_ID)
    stats = Stats()
    context = make_context(settings, stats=stats, users=users if users is not None else {})
    context.bot_data["semaphore"] = asyncio.Semaphore(2)
    return settings, stats, context


async def test_access_denied_is_counted(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={})
    update = make_update(VALID_URL, user_id=999)  # asing di mode private
    await download_handler(update, context)
    assert update.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED
    assert stats.rejected_reasons == {"access_denied": 1}


async def test_unsupported_url_is_counted(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    update = make_update(UNSUPPORTED_URL, user_id=OWNER_ID)
    await download_handler(update, context)
    assert stats.rejected_reasons == {"unsupported_url": 1}


async def test_rate_limited_is_counted_once(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    limiter: UserRateLimiter = context.bot_data["rate_limiter"]
    limiter.time_source = lambda: 0.0

    with patch.object(download_mod.asyncio, "create_task") as task_spy:
        first = make_update(VALID_URL, user_id=OWNER_ID)
        await download_handler(first, context)
        task_spy.call_args.args[0].close()  # jangan jalankan job-nya
        assert stats.rejected_reasons == {}, "permintaan pertama lolos, bukan penolakan"

        second = make_update(VALID_URL, user_id=OWNER_ID)
        await download_handler(second, context)
        assert stats.rejected_reasons == {"rate_limited": 1}
        assert "Terlalu sering" in second.message.reply_text.call_args.args[0]


async def test_plain_text_without_url_is_not_counted(tmp_path):
    """PLAN T-164: teks tanpa URL hanya minta ulang, BUKAN penolakan."""
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    update = make_update("halo dunia", user_id=OWNER_ID)
    await download_handler(update, context)
    assert stats.rejected == 0
    assert stats.rejected_reasons == {}
    assert stats.processed == 0


async def test_successful_job_increments_processed(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    result = DownloadResult(
        path=Path(_settings.download_dir) / "v.mp4", metadata={"title": "contoh"}
    )
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(downloader_service, "download", AsyncMock(return_value=result)),
        patch.object(download_mod, "send_video", AsyncMock()),
    ):
        await download_handler(make_update(VALID_URL, user_id=OWNER_ID), context)
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=DRAIN_TIMEOUT)

    assert stats.processed == 1
    assert stats.rejected == 0


async def test_failed_job_counts_download_failed_not_processed(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    async def boom(url, _settings):
        raise DownloadFailedError("simulasi yt-dlp mati")

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(downloader_service, "download", boom),
    ):
        await download_handler(make_update(VALID_URL, user_id=OWNER_ID), context)
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=DRAIN_TIMEOUT)

    assert stats.rejected_reasons == {"download_failed": 1}
    assert stats.processed == 0


async def test_failed_upload_counts_download_failed_not_processed(tmp_path):
    _settings, stats, context = _download_context(tmp_path, users={OWNER_ID: "Owner"})
    result = DownloadResult(path=Path(_settings.download_dir) / "v.mp4", metadata={})
    jobs: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def spy(coro):
        task = real_create_task(coro)
        jobs.append(task)
        return task

    async def bad_upload(**kwargs):
        raise UploadError("upload ditolak")

    with (
        patch.object(download_mod.asyncio, "create_task", side_effect=spy),
        patch.object(downloader_service, "download", AsyncMock(return_value=result)),
        patch.object(download_mod, "send_video", bad_upload),
    ):
        await download_handler(make_update(VALID_URL, user_id=OWNER_ID), context)
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=DRAIN_TIMEOUT)

    assert stats.processed == 0
    assert stats.rejected_reasons == {"download_failed": 1}


async def test_download_handler_without_stats_key_is_unaffected(tmp_path):
    """206 test lama tidak tahu soal stats: bot_data tanpa kunci `stats` tetap jalan."""
    settings = make_settings(tmp_path, bot_mode="public")
    context = MagicMock()
    context.bot_data = {"rate_limiter": UserRateLimiter(10), "settings": settings}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    update = make_update(UNSUPPORTED_URL, user_id=OWNER_ID)
    await download_handler(update, context)
    assert update.message.reply_text.await_count == 1


# ---------------- T-168: verifikasi khusus WP-16 ----------------


def test_create_task_for_notifications_lives_only_in_start_module():
    """PLAN T-168: `create_task` notifikasi stats HANYA di `app/handlers/start.py`.

    Sumber dibaca lewat `inspect.getsource` (modul yang benar-benar ter-import),
    bukan `grep` path, jadi bukti tidak bisa basi oleh perbedaan lokasi.
    """
    start_src = inspect.getsource(start_mod)
    download_src = inspect.getsource(download_mod)
    account_src = inspect.getsource(account_mod)

    assert "notify_new_user" in start_src
    assert "asyncio.create_task" in start_src
    # `download.py` tetap punya create_task lamanya (milik WP-06..WP-10) tapi
    # tidak boleh ada notifikasi stats di sana.
    assert "notify_new_user" not in download_src
    assert "notify_new_user" not in account_src
    assert download_src.count("asyncio.create_task(") == 1


def test_wp16_sources_have_no_typographic_dashes():
    """Garis merah repo: file tracked tanpa U+2014/U+2013 (PLAN §5a / aturan WP)."""
    paths = [
        "app/services/stats.py",
        "app/handlers/start.py",
        "app/handlers/account.py",
        "app/handlers/download.py",
        "app/main.py",
        "tests/test_stats.py",
    ]
    for rel in paths:
        text = Path(rel).read_text(encoding="utf-8")
        assert "\u2014" not in text, f"em-dash ditemukan di {rel}"
        assert "\u2013" not in text, f"en-dash ditemukan di {rel}"


def test_menu_text_lists_stats_command(tmp_path):
    """Konsistensi WP-15: `/stats` sudah disebut di teks `/menu` (FR-016)."""
    from app.services.access import menu_text

    settings = make_settings(tmp_path, bot_mode="public")
    assert "/stats" in menu_text(settings, OWNER_ID, {})


# ---------------- T-166: wiring `app/main.py` ----------------


def _fake_application(monkeypatch, conf):
    """Pasang builder palsu untuk `main()`; kembalikan objek application+application cls."""
    from app import main as main_mod

    application = MagicMock()
    application.bot_data = {}
    application.initialize = AsyncMock()
    application.start = AsyncMock()
    application.updater.start_polling = AsyncMock()
    application.updater.stop = AsyncMock()
    application.stop = AsyncMock()
    application.shutdown = AsyncMock()

    builder = MagicMock()
    builder.token.return_value.build.return_value = application
    fake_application = MagicMock()
    fake_application.builder.return_value = builder
    monkeypatch.setattr(main_mod, "Application", fake_application)
    monkeypatch.setattr(main_mod, "get_settings", lambda: conf)
    return main_mod, application


async def _run_main_until_polling(application) -> None:
    """Jalankan `main()` sampai polling 'mulai', lalu batalkan task-nya."""
    from app import main as main_mod

    run = asyncio.create_task(main_mod.main())
    for _ in range(20):
        await asyncio.sleep(0)
        if application.updater.start_polling.await_count:
            break
    assert application.updater.start_polling.await_count == 1
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run


async def test_main_wires_stats_and_post_shutdown(tmp_path, monkeypatch):
    """`bot_data['stats']` terisi sebelum handler; `post_shutdown` = flush stats."""
    conf = make_settings(tmp_path, bot_mode="public", admin_notify_chat_id=ADMIN_CHAT)
    main_mod, application = _fake_application(monkeypatch, conf)
    await _run_main_until_polling(application)

    assert isinstance(application.bot_data["stats"], Stats)
    assert application.post_shutdown is main_mod._flush_stats

    # Atribut ptb 22.8: `CommandHandler.commands` = frozenset; `MessageHandler`
    # tidak punya atribut itu (dibaca dari objek aslinya, bukan asumsi).
    registered = {
        name
        for call in application.add_handler.call_args_list
        for name in getattr(call.args[0], "commands", ())
    }
    assert "stats" in registered
    stats_handler = next(
        call.args[0]
        for call in application.add_handler.call_args_list
        if "stats" in getattr(call.args[0], "commands", ())
    )
    assert stats_handler.callback is main_mod.stats_command


async def test_main_restores_known_users_from_disk(tmp_path, monkeypatch):
    """Integrasi: `stats.json` lama tetap terbaca saat startup (persistensi SC 17)."""
    conf = make_settings(tmp_path, bot_mode="public")
    before = Stats()
    before.record_user(555)
    assert before.save(conf.stats_file) is True

    main_mod, application = _fake_application(monkeypatch, conf)
    await _run_main_until_polling(application)

    stats_obj = application.bot_data["stats"]
    assert stats_obj.total_users == 1
    assert stats_obj.record_user(555) is False
    assert stats_obj.record_user(555, first_name="X", username="x") is False
    assert main_mod  # menjaga agar import tetap dipakai bila assertion di atas diubah


async def test_flush_stats_persists_counters(tmp_path):
    from app import main as main_mod

    stats = Stats()
    stats.record_user(7)
    stats.record_user(8)
    stats.inc_processed()
    stats.inc_rejected("rate_limited")
    settings = make_settings(tmp_path, bot_mode="public")
    application = MagicMock()
    application.bot_data = {"stats": stats, "settings": settings}

    await main_mod._flush_stats(application)

    data = _read_json(settings.stats_file)
    assert data["total_users"] == 2
    assert sorted(data["first_seen"]) == ["7", "8"]
    assert data["processed"] == 1
    assert data["rejected_reasons"] == {"rate_limited": 1}
    assert stat.S_IMODE(os.stat(settings.stats_file).st_mode) == 0o600
    assert _leftover_tmp(tmp_path) == []


async def test_flush_stats_noops_without_stats_or_path(tmp_path, monkeypatch):
    """Dua jalur no-op `post_shutdown`: tanpa kunci stats, dan settings tanpa `stats_file`.

    `bot_data["settings"]` model `SimpleNamespace` mewakili objek settings parsial
    (test WP-11 membangun `Settings.model_construct()` sendiri): `getattr(..., None)`
    harus membuat flush dilewati, bukan menulis `stats.json` ke CWD.
    """
    from app import main as main_mod

    # CWD dipindah ke tmp_path supaya "tidak ada penulisan" bisa DIBUKTIKAN.
    monkeypatch.chdir(tmp_path)

    no_path = MagicMock()
    no_path.bot_data = {"stats": Stats(), "settings": SimpleNamespace()}
    await main_mod._flush_stats(no_path)
    assert not (tmp_path / "stats.json").exists()

    empty = MagicMock()
    empty.bot_data = {}
    await main_mod._flush_stats(empty)
    assert not (tmp_path / "stats.json").exists()
    assert _leftover_tmp(tmp_path) == []
