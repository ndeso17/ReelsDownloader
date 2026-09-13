"""Handler akun & akses: `/getID` (FR-012), `/menu` (FR-016), `/setUser` (FR-014).

`/getID` dan `/menu` PUBLIK di kedua mode (PRD §4). `/setUser` admin-only dan
hanya aktif di private mode. Guard `/setUser` berurutan dan TIDAK bisa dilewati:
tanpa guard, `/setUser` = penulisan daftar whitelist oleh siapa pun.

Semua mutasi file lewat `asyncio.to_thread` (AGENTS.md §4.4: I/O blocking).

Serialisasi transaksi (REWORK-R3): `asyncio.to_thread` hanya memindahkan I/O ke thread
pool, ia TIDAK mengantrikan dua panggilan handler. Karena itu baca-daftar -> ubah ->
tulis -> tulis-balik ke `bot_data["users"]` dibungkus satu `asyncio.Lock`:
`bot_data["access_lock"]` bila tersedia (dibuat `app/main.py`), selain itu kunci per
jalur berkas dari `write_lock_for`. Tanpa kunci itu, dua `/setUser` serentak saling
menimpa hasil JSON (lost update; probe race QC lama: 2/12 BAD).
"""

from __future__ import annotations

import asyncio
import logging
import os

from telegram.ext import ContextTypes

from app.services import user_store
from app.services.access import (
    MSG_ACCESS_DENIED,
    MSG_GETID,
    MSG_SETUSER_ADDED,
    MSG_SETUSER_INACTIVE,
    MSG_SETUSER_LIST_EMPTY,
    MSG_SETUSER_LIST_HEADER,
    MSG_SETUSER_NEED_PRIVATE_OWNER,
    MSG_SETUSER_REMOVED,
    MSG_SETUSER_USAGE,
    is_owner,
    menu_text,
)

logger = logging.getLogger(__name__)

__all__ = ["get_id", "menu", "set_user", "write_lock_for"]

#: Kunci cadangan per jalur berkas whitelist, dipakai bila `bot_data` tidak menyediakan
#: `access_lock` (mis. test yang membangun `context` manual). `dict.setdefault` atomik
#: di CPython dan seluruh akses terjadi di satu event loop, jadi tidak perlu mutex.
_WRITE_LOCKS: dict[str, asyncio.Lock] = {}


def write_lock_for(users_file: str | os.PathLike[str]) -> asyncio.Lock:
    """Kembalikan (atau buat) `asyncio.Lock` untuk satu jalur berkas whitelist.

    Per path, bukan global: dua berkas berbeda tidak boleh saling menahan.
    """
    key = os.fspath(users_file)
    lock = _WRITE_LOCKS.get(key)
    if lock is None:
        lock = _WRITE_LOCKS.setdefault(key, asyncio.Lock())
    return lock


def _access_lock(context, users_file: str | os.PathLike[str]) -> asyncio.Lock:
    """Kunci transaksi untuk satu tulis whitelist: `access_lock` bot, else kunci per path."""
    lock = context.bot_data.get("access_lock")
    if isinstance(lock, asyncio.Lock):
        return lock
    return write_lock_for(users_file)


def _user_id_of(update):
    user = getattr(update, "effective_user", None)
    return getattr(user, "id", None) if user is not None else None


async def get_id(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-012 (publik): balas ID numerik pengirim sendiri, tidak pernah ID orang lain."""
    user_id = _user_id_of(update)
    await update.effective_message.reply_text(MSG_GETID.format(user_id=user_id))


async def menu(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-016 (publik): daftar command v2.2 + status akses pengirim."""
    settings = context.bot_data["settings"]
    users = context.bot_data.get("users", {})
    text = menu_text(settings, _user_id_of(update), users)
    await update.effective_message.reply_text(text)


def _label_of(update, user_id: int) -> str:
    """Label tampilan user: `first_name (@username)` bila pengirim mendaftarkan dirinya."""
    user = getattr(update, "effective_user", None)
    if user is None or getattr(user, "id", None) != user_id:
        return ""
    first = getattr(user, "first_name", None) or ""
    username = getattr(user, "username", None)
    return f"{first} (@{username})" if username else first


async def set_user(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-014: `/setUser add|remove|list <id>`; admin-only, hanya private mode."""
    settings = context.bot_data["settings"]
    users: dict[int, str] = context.bot_data.get("users", {})
    actor_id = _user_id_of(update)

    # (1) Public mode: command tidak aktif, daftar tidak berubah.
    if getattr(settings, "bot_mode", "public") != "private":
        await update.effective_message.reply_text(MSG_SETUSER_INACTIVE)
        return

    # (2) Bukan owner: tolak, jangan sentuh daftar.
    if not is_owner(actor_id, settings):
        logger.warning("percobaan /setUser bukan admin: user_id=%s", actor_id)
        await update.effective_message.reply_text(MSG_ACCESS_DENIED)
        return

    parts = context.args or []
    command = parts[0].lower() if parts else ""

    # (3) list: murni baca, tidak menyentuh disk -> tanpa kunci transaksi.
    if command == "list":
        lines = [MSG_SETUSER_LIST_HEADER.format(total=user_store.count(users))]
        if not users:
            lines.append(MSG_SETUSER_LIST_EMPTY.format(total=0))
        for user_id in sorted(users):
            lines.append(f"- {user_id}: {users[user_id]}")
        await update.effective_message.reply_text("\n".join(lines))
        return

    # (4) add/remove: argumen target harus ID numerik sebelum ada mutasi.
    try:
        target_id = int(parts[1])
    except (IndexError, ValueError):
        await update.effective_message.reply_text(MSG_SETUSER_USAGE)
        return

    # (5) Mutasi owner terlarang: ditolak sebelum ada perubahan state.
    if command == "remove" and is_owner(target_id, settings):
        await update.effective_message.reply_text(MSG_SETUSER_NEED_PRIVATE_OWNER)
        return

    if command not in ("add", "remove"):
        await update.effective_message.reply_text(MSG_SETUSER_USAGE)
        return

    # (6) Transaksi read-modify-write terserialisasi per berkas (REWORK-R3). Snapshot
    # dibaca ULANG di dalam kunci: snapshot saat handler masuk bisa sudah basi bila
    # transaksi lain selesai lebih dulu, dan menulis snapshot basi = lost update.
    users_file = getattr(settings, "users_file", None) or "users.json"
    async with _access_lock(context, users_file):
        logger.info("setUser %s target=%s by=%s", command, target_id, actor_id)
        current: dict[int, str] = context.bot_data.get("users", {})
        if command == "add":
            updated = user_store.add_user(current, target_id, _label_of(update, target_id))
        else:
            updated = user_store.remove_user(current, target_id)
        saved = await asyncio.to_thread(user_store.save_users, users_file, updated)
        context.bot_data["users"] = updated
        reply = (
            MSG_SETUSER_ADDED.format(user_id=target_id)
            if command == "add"
            else MSG_SETUSER_REMOVED.format(user_id=target_id)
        )

    # (7) Persist gagal: beri tahu; in-memory tetap (bot tidak boleh mati karena disk).
    if not saved:
        logger.error("gagal persist whitelist ke %s", users_file)
        reply += "\nGagal menyimpan ke berkas; perubahan hilang saat bot restart."

    await update.effective_message.reply_text(reply)
