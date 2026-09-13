"""Test WP-15 (T-158): config v2.2 + access layer whitelist (FR-012..FR-016).

Pola test sama WP-06/WP-08: `update`/`context` MagicMock/AsyncMock, tidak ada
network, tidak ada akses Instagram/Facebook nyata (AGENTS.md §4.6). Semua token
di file ini string dummy pendek (AGENTS.md §5a).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
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

    with patch.object(download_mod.asyncio, "create_task") as mock_task:
        await download_handler(update, context)

    assert update.message.reply_text.call_args.args[0] == MSG_ACCESS_DENIED
    limiter.acquire.assert_not_called()
    mock_task.assert_not_called()


# ---------------- (l) public tanpa kunci `users` -> jalur lama, ack muncul ----------------


async def test_download_public_without_users_key_still_acks(tmp_path):
    settings = make_settings(tmp_path, bot_mode="public")
    update = make_update(VALID_URL, user_id=555)
    context = MagicMock()
    context.bot_data = {"rate_limiter": UserRateLimiter(10), "settings": settings}
    assert "users" not in context.bot_data
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    with patch.object(download_mod.asyncio, "create_task") as mock_task:
        await download_handler(update, context)

    assert any("⏳" in c.args[0] for c in update.message.reply_text.call_args_list)
    mock_task.assert_called_once()
    mock_task.call_args.args[0].close()


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
    assert fake_replace.call_args.args[0] == str(path) + ".tmp"
    # save gagal (OSError) -> False, tidak raise
    with patch("app.services.user_store.open", side_effect=OSError("read-only")):
        assert user_store.save_users(tmp_path / "other.json", users) is False

    assert user_store.count(users) == 2
    assert user_store.add_user({}, 7, "x") == {7: "x"} and users == {
        42: "Budi (@budi)",
        9876543210123: "ID besar",
    }
    assert user_store.remove_user({7: "x"}, 7) == {}


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
