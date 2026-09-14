"""Test WP-15 (T-158): config v2.2 + access layer whitelist (FR-012..FR-016).

Pola test sama WP-06/WP-08: `update`/`context` MagicMock/AsyncMock, tidak ada
network, tidak ada akses Instagram/Facebook nyata (AGENTS.md §4.6). Semua token
di file ini string dummy pendek (AGENTS.md §5a).
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.handlers import account as account_mod
from app.handlers import download as download_mod
from app.handlers.account import get_id, menu, set_user
from app.handlers.download import download_handler
from app.services import user_store
from app.services.access import (
    MSG_ACCESS_DENIED,
    MSG_GETID,
    MSG_SETUSER_INACTIVE,
    can_download,
    effective_ids,
    is_owner,
    menu_text,
)
from app.services.rate_limiter import UserRateLimiter

VALID_URL = "https://www.instagram.com/reel/xxxxx/"
DUMMY_TOKEN = SecretStr(" ".join(["dummy", "token"]))  # bukan kredensial nyata


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings sah (lewat validator penuh) dengan download_dir sementara."""
    download_dir = tmp_path / "dl"
    download_dir.mkdir(exist_ok=True)
    base = {
        "telegram_bot_token": DUMMY_TOKEN,
        "download_dir": str(download_dir),
        "users_file": str(tmp_path / "users.json"),
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def make_update(text: str = "", user_id: int | None = 999) -> MagicMock:
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


def make_context(settings: Settings, users: dict[int, str] | None = None, **extra) -> MagicMock:
    context = MagicMock()
    bot_data = {"rate_limiter": UserRateLimiter(10), "settings": settings}
    if users is not None:
        bot_data["users"] = users
    bot_data.update(extra)
    context.bot_data = bot_data
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []
    return context


# ---------------- (a) public mode: user asing boleh download ----------------


def test_public_mode_always_allows_download(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public")
    assert can_download(4242, settings, {}) is True
    assert can_download(None, settings, {}) is True


# ---------------- (b) private mode: owner/seed/file boleh, asing tidak ----------------


def test_private_mode_effective_ids_union(tmp_path):
    settings = make_settings(
        tmp_path,
        bot_mode="private",
        owner_user_id=111,
        authorized_user_ids="222, 333",
    )
    users = {444: "Budi (@budi)"}
    ids = effective_ids(settings, users)
    assert ids == frozenset({111, 222, 333, 444})
    assert can_download(111, settings, users) is True  # owner
    assert can_download(222, settings, users) is True  # seed env
    assert can_download(444, settings, users) is True  # users file
    assert can_download(555, settings, users) is False  # asing
    assert is_owner(111, settings) is True
    assert is_owner(222, settings) is False
    assert can_download(None, settings, users) is False


def test_private_mode_empty_list_is_fail_closed(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    assert can_download(999, settings, {}) is False


def test_authorized_ids_set_rejects_non_numeric_token(tmp_path):
    settings = make_settings(tmp_path, authorized_user_ids="123, abc")
    with pytest.raises(ValueError):
        settings.authorized_ids_set()


# ---------------- (c)(d) /getID publik ----------------


async def test_get_id_replies_exact_effective_user_id(tmp_path):
    update = make_update("/getID", user_id=987654321)
    context = make_context(make_settings(tmp_path))
    await get_id(update, context)
    assert update.message.reply_text.call_args.args[0] == MSG_GETID.format(user_id=987654321)


async def test_get_id_works_for_stranger_in_private_mode(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    update = make_update("/getID", user_id=555)
    await get_id(update, make_context(settings, users={}))
    assert "555" in update.message.reply_text.call_args.args[0]


# ---------------- (e) /menu: 3 varian status ----------------


async def test_menu_status_variants(tmp_path):
    public = make_settings(tmp_path, bot_mode="public")
    private = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    assert "Status akses Anda: Publik" in menu_text(public, 555, {})
    assert "Status akses Anda: Terdaftar" in menu_text(private, 111, {})
    assert "Status akses Anda: Tidak terdaftar" in menu_text(private, 555, {})
    # /menu menjawab untuk siapa pun (publik), termasuk user asing di private mode
    update = make_update("/menu", user_id=555)
    await menu(update, make_context(private, users={}))
    assert "Status akses Anda: Tidak terdaftar" in update.message.reply_text.call_args.args[0]


# ---------------- (f) /setUser public -> tidak aktif, tanpa simpan ----------------


async def test_set_user_inactive_in_public_mode(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public", owner_user_id=111)
    update = make_update("/setUser add 42", user_id=111)
    context = make_context(settings, users={})
    context.args = ["add", "42"]
    with patch.object(user_store, "save_users") as fake_save:
        await set_user(update, context)
    assert update.message.reply_text.call_args.args[0] == MSG_SETUSER_INACTIVE
    fake_save.assert_not_called()
    assert context.bot_data["users"] == {}


# ---------------- (g) /setUser add oleh owner -> persist ----------------


async def test_set_user_add_persists_and_reloads(tmp_path):
    settings = make_settings(
        tmp_path, bot_mode="private", owner_user_id=111, users_file=str(tmp_path / "users.json")
    )
    update = make_update("/setUser add 42", user_id=111)
    context = make_context(settings, users={})
    context.args = ["add", "42"]

    await set_user(update, context)

    assert "42" in update.message.reply_text.call_args.args[0]
    assert context.bot_data["users"][42] == ""
    # persist: dibaca ulang dari disk = sama (bukti restart, SC 13)
    assert user_store.load_users(settings.users_file) == {42: ""}


# ---------------- (h) /setUser remove owner -> ditolak, daftar utuh ----------------


async def test_set_user_cannot_remove_owner(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    update = make_update("/setUser remove 111", user_id=111)
    context = make_context(settings, users={42: "Budi (@budi)"})
    context.args = ["remove", "111"]

    await set_user(update, context)

    assert "Owner tidak bisa dihapus" in update.message.reply_text.call_args.args[0]
    assert context.bot_data["users"] == {42: "Budi (@budi)"}


# ---------------- (i) /setUser add abc -> teks penggunaan, tanpa mutasi ----------------


async def test_set_user_non_numeric_id_replies_usage(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    update = make_update("/setUser add abc", user_id=111)
    context = make_context(settings, users={})
    context.args = ["add", "abc"]

    await set_user(update, context)

    reply = update.message.reply_text.call_args.args[0]
    assert "ID harus angka" in reply
    assert context.bot_data["users"] == {}


# ---------------- (j) non-admin private -> MSG_ACCESS_DENIED, tanpa mutasi ----------------


async def test_set_user_denied_for_non_admin(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    update = make_update("/setUser add 42", user_id=555)
    context = make_context(settings, users={})
    context.args = ["add", "42"]

    await set_user(update, context)

    assert update.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED
    assert context.bot_data["users"] == {}


# ---------------- (k) gerbang akses sebelum rate limiter ----------------


async def test_download_gate_blocks_stranger_before_rate_limiter(tmp_path):
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    update = make_update(VALID_URL, user_id=555)
    limiter = UserRateLimiter(10)
    limiter.acquire = AsyncMock()
    context = make_context(settings, users={}, rate_limiter=limiter)

    with patch.object(download_mod, "build_job", wraps=download_mod.build_job) as build_spy:
        await download_handler(update, context)

    assert update.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED
    limiter.acquire.assert_not_called()
    assert build_spy.call_count == 0, "pekerjaan tidak dijadwalkan saat access denied"


# ---------------- (l) public tanpa kunci `users` -> jalur lama, ack muncul ----------------


async def test_download_public_without_users_key_still_acks(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public")
    update = make_update(VALID_URL, user_id=555)
    context = MagicMock()
    context.bot_data = {"rate_limiter": UserRateLimiter(10), "settings": settings}
    assert "users" not in context.bot_data
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    with patch.object(download_mod, "build_job", wraps=download_mod.build_job) as build_spy:
        await download_handler(update, context)

    assert any("⏳" in c.args[0] for c in update.message.reply_text.call_args_list)
    assert build_spy.call_count == 1, "pekerjaan dijadwalkan di jalur public"


# ---------------- (m) round-trip user_store ----------------


def test_user_store_roundtrip_corrupt_and_atomic(tmp_path):
    path = tmp_path / "users.json"
    users = {42: "Budi (@budi)", 9876543210123: "ID besar"}

    assert user_store.save_users(path, users) is True
    assert user_store.load_users(path) == users
    # kunci ditulis sebagai string desimal (kompatibel semua klien JSON)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"42", "9876543210123"}

    # file rusak -> {} tanpa raise
    path.write_text("{ ini bukan json", encoding="utf-8")
    assert user_store.load_users(path) == {}
    # hilang -> {} tanpa raise
    assert user_store.load_users(tmp_path / "nope.json") == {}

    # atomik: os.replace dipanggil, bukan tulis langsung ke path final
    with patch("app.services.user_store.os.replace") as fake_replace:
        assert user_store.save_users(path, users) is True
    fake_replace.assert_called_once()
    src, dst = fake_replace.call_args.args
    assert dst == str(path)  # tujuan rename = path final
    assert src != str(path)  # tmp BUKAN path final (tulis tidak langsung)
    assert os.path.dirname(os.path.abspath(src)) == str(tmp_path)  # tmp serumah
    # REWORK-R3: tmp unik per penulisan, bukan nama tetap `<path>.tmp` yang identik
    # untuk semua penulis (nama tetap itulah yang bikin dua tulis interleave).
    assert src != str(path) + ".tmp"
    assert os.path.basename(src).startswith(os.path.basename(path) + ".")
    assert src.endswith(".tmp")
    # save gagal (OSError) -> False, tidak raise
    with patch("app.services.user_store.open", side_effect=OSError("read-only")):
        assert user_store.save_users(tmp_path / "other.json", users) is False

    assert user_store.count(users) == 2
    assert user_store.add_user({}, 7, "x") == {7: "x"} and users == {
        42: "Budi (@budi)",
        9876543210123: "ID besar",
    }
    assert user_store.remove_user({7: "x"}, 7) == {}


# ---------------- REWORK-R1..R3: mode 0600, fsync, tmp unik, serialisasi ----------------


def test_save_users_mode_is_0600(tmp_path):
    """REWORK-R1: berkas final 0600 (bukan 0664 warisan umask), termasuk saat sudah ada."""
    path = tmp_path / "users.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0o644)  # pra-ada dengan mode longgar -> save harus menormalkan

    assert user_store.save_users(path, {42: "Budi"}) is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    # Penulisan kedua (replace menimpa) tetap 0600, bukan mode tmp lain.
    assert user_store.save_users(path, {42: "Budi", 43: "Ani"}) is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_save_users_fsyncs_file_before_replace(tmp_path):
    """REWORK-R2: flush + `os.fsync(fd)` SEBELUM `os.replace` (yang dikunci = urutan)."""
    path = tmp_path / "users.json"
    order: list[str] = []

    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd):
        order.append("fsync")
        return real_fsync(fd)

    def spy_replace(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    with (
        patch("app.services.user_store.os.fsync", side_effect=spy_fsync),
        patch("app.services.user_store.os.replace", side_effect=spy_replace),
    ):
        assert user_store.save_users(path, {7: "x"}) is True

    assert order.count("fsync") >= 1  # berkas (dan idealnya direktori) di-fsync
    assert order.index("fsync") < order.index("replace")  # fsync sebelum rename
    assert user_store.load_users(path) == {7: "x"}


def test_save_users_fsyncs_parent_dir_after_replace(tmp_path):
    """REWORK-R2: `fsync` direktori parent dipanggil setelah rename (durability entri)."""
    path = tmp_path / "users.json"
    order: list[str] = []

    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd):
        try:
            is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        except OSError:
            is_dir = False
        order.append("fsync_dir" if is_dir else "fsync_file")
        return real_fsync(fd)

    def spy_replace(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    with (
        patch("app.services.user_store.os.fsync", side_effect=spy_fsync),
        patch("app.services.user_store.os.replace", side_effect=spy_replace),
    ):
        assert user_store.save_users(path, {7: "x"}) is True

    assert "fsync_file" in order
    assert "fsync_dir" in order
    assert order.index("fsync_file") < order.index("replace")
    assert order.index("replace") < order.index("fsync_dir")


def test_save_users_dir_fsync_failure_does_not_break_save(tmp_path):
    """REWORK-R2: platform yang menolak fsync direktori tidak boleh menggagalkan save."""
    path = tmp_path / "users.json"
    real_fsync = os.fsync  # capture SEBELUM patch (patch menyentuh os module yang sama)

    def fake_fsync(fd):
        try:
            is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        except OSError:
            is_dir = False
        if is_dir:
            raise OSError("EINVAL: dir fsync ditolak")
        return real_fsync(fd)

    with patch("app.services.user_store.os.fsync", side_effect=fake_fsync):
        assert user_store.save_users(path, {5: "y"}) is True
    assert user_store.load_users(path) == {5: "y"}


def test_save_users_concurrent_same_path_tmp_never_collides(tmp_path):
    """REWORK-R3 (unit): dua save serentak dari dua thread, dua-duanya sukses, tmp unik."""
    path = tmp_path / "users.json"
    tmp_sources: list[str] = []
    lock = threading.Lock()
    real_replace = os.replace

    def spy_replace(src, dst):
        with lock:
            tmp_sources.append(str(src))
        return real_replace(src, dst)

    results: list[bool] = []

    def worker(i: int) -> None:
        results.append(user_store.save_users(path, {i: f"user{i}"}))

    with patch("app.services.user_store.os.replace", side_effect=spy_replace):
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert results == [True] * 8
    assert len(tmp_sources) == 8
    assert len(set(tmp_sources)) == 8  # tidak ada tmp path yang dipakai dua kali
    assert user_store.load_users(path)  # JSON final valid (tidak korup)
    assert not list(tmp_path.glob("*.tmp"))  # tidak ada tmp yatim


def _read_json_file(path: str) -> dict:
    """Baca + parse JSON di fungsi sync (hindari blocking call di body async)."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _unlink_if_exists(path: str) -> None:
    """Hapus berkas bila ada (sync helper, sama alasannya dengan `_read_json_file`)."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _leftover_tmp(dir_path: str) -> list:
    """Daftar sisa berkas `.tmp` di direktori (sync helper)."""
    return sorted(name for name in os.listdir(dir_path) if name.endswith(".tmp"))


def _ctx_with_args(context, args: list[str]) -> MagicMock:
    """Context baru dengan `bot_data` SHARED dan `args` sendiri (per update, PTB asli).

    `context.args` di PTB per-update; memakai satu context untuk banyak task serentak
    akan membuat `args` saling tertimpa dan test tidak lagi mewakili produksi.
    """
    ctx = MagicMock()
    ctx.bot_data = context.bot_data  # state bot = satu objek, seperti PTB
    ctx.bot = context.bot
    ctx.args = args
    return ctx


async def test_set_user_heavy_concurrent_race_no_lost_update(tmp_path):
    """REWORK-R3 (integrasi): 10 ronde x 8 `/setUser add` serentak -> file valid, 8 user utuh.

    Probe race QC lama (tmp path identik + tanpa kunci) menghasilkan 2/12 BAD: satu
    `json.JSONDecodeError` (dua tulis menginterleave satu berkas tmp) dan satu lost
    update (6/8 key). Loop 10 ronde menekan peluang lulus kebetulan.
    """
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    context = make_context(settings, users={})

    users_file = settings.users_file

    for round_index in range(10):
        context.bot_data["users"] = {}
        _unlink_if_exists(users_file)

        targets = [5000 + round_index * 100 + offset for offset in range(8)]
        jobs = []
        for target in targets:
            update = make_update(f"/setUser add {target}", user_id=111)
            jobs.append(set_user(update, _ctx_with_args(context, ["add", str(target)])))

        await asyncio.gather(*jobs)

        # `_read_json_file` = `json.load` asli: JSONDecodeError langsung FAIL (interleave)
        on_disk = _read_json_file(users_file)
        assert len(on_disk) == 8, f"round {round_index}: lost update, {len(on_disk)}/8 key"
        for target in targets:
            assert str(target) in on_disk
        assert user_store.load_users(users_file) == context.bot_data["users"]
        assert stat.S_IMODE(os.stat(users_file).st_mode) == 0o600
        assert _leftover_tmp(str(tmp_path)) == []


async def test_set_user_concurrent_keeps_memory_and_disk_in_sync(tmp_path):
    """REWORK-R3: snapshot memori == isi berkas setelah banyak add/remove serentak."""
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    context = make_context(settings, users={})

    jobs = [
        set_user(
            make_update(f"/setUser add {7000 + i}", user_id=111),
            _ctx_with_args(context, ["add", str(7000 + i)]),
        )
        for i in range(6)
    ]
    await asyncio.gather(*jobs)

    jobs = [
        set_user(
            make_update(f"/setUser remove {7000 + i}", user_id=111),
            _ctx_with_args(context, ["remove", str(7000 + i)]),
        )
        for i in range(3)
    ]
    await asyncio.gather(*jobs)

    assert context.bot_data["users"] == user_store.load_users(settings.users_file)
    assert sorted(context.bot_data["users"]) == [7003, 7004, 7005]
    assert stat.S_IMODE(os.stat(settings.users_file).st_mode) == 0o600


def test_write_lock_for_is_per_path_and_stable(tmp_path):
    """REWORK-R3: kunci per berkas, objek sama untuk path sama, beda untuk path beda."""
    lock_a = account_mod.write_lock_for(str(tmp_path / "a" / "users.json"))
    lock_b = account_mod.write_lock_for(str(tmp_path / "a" / "users.json"))
    lock_c = account_mod.write_lock_for(str(tmp_path / "b" / "users.json"))
    assert lock_a is lock_b
    assert lock_a is not lock_c
    assert isinstance(lock_a, asyncio.Lock)


async def test_access_lock_from_bot_data_is_used(tmp_path):
    """REWORK-R3: `bot_data["access_lock"]` (dibuat main.py) benar-benar dipakai handler."""
    settings = make_settings(tmp_path, bot_mode="private", owner_user_id=111)
    context = make_context(settings, users={})
    sentinel = asyncio.Lock()
    context.bot_data["access_lock"] = sentinel

    seen: list[bool] = []
    real_save = user_store.save_users

    def spy_save(path, users):
        seen.append(sentinel.locked())  # lock wajib sedang dipegang saat menulis
        return real_save(path, users)

    update = make_update("/setUser add 4242", user_id=111)
    context.args = ["add", "4242"]
    with patch.object(user_store, "save_users", side_effect=spy_save):
        await set_user(update, context)

    assert seen == [True]


# ---------------- T-151: validasi config v2.2 ----------------


def test_settings_queue_bounds_and_private_owner_required(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, queue_max_size=0)
    with pytest.raises(ValidationError):
        make_settings(tmp_path, max_queue_wait_seconds=0)
    with pytest.raises(ValidationError):
        make_settings(tmp_path, bot_mode="private")  # owner wajib
    ok = make_settings(tmp_path, bot_mode="private", owner_user_id=7)
    assert ok.owner_user_id == 7
    assert ok.admin_chat_id == 7  # fallback owner


def test_settings_empty_int_strings_become_none(tmp_path):
    s = make_settings(tmp_path, owner_user_id="", admin_notify_chat_id="")
    assert s.owner_user_id is None
    assert s.admin_notify_chat_id is None
    assert s.admin_chat_id is None
    s2 = make_settings(tmp_path, admin_notify_chat_id=31337, owner_user_id=7)
    assert s2.admin_chat_id == 31337


def test_settings_extra_forbid_still_active(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, tiktik_mode="on")
