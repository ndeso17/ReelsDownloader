"""Handler akun & akses: `/getID` (FR-012), `/menu` (FR-016), `/setUser` (FR-014).

`/getID` dan `/menu` PUBLIK di kedua mode (PRD §4). `/setUser` admin-only dan
hanya aktif di private mode. Guard `/setUser` berurutan dan TIDAK bisa dilewati:
tanpa guard, `/setUser` = penulisan daftar whitelist oleh siapa pun.

Semua mutasi file lewat `asyncio.to_thread` (AGENTS.md §4.4: I/O blocking).
"""

from __future__ import annotations

import asyncio
import logging

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

__all__ = ["get_id", "menu", "set_user"]


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

    args = list(getattr(context, "args", None) or [])
    action = args[0].lower() if args else ""

    if action == "list":
        await update.effective_message.reply_text(_render_list(users))
        return

    if action not in ("add", "remove") or len(args) < 2:
        await update.effective_message.reply_text(MSG_SETUSER_USAGE)
        return

    # (3) Argumen tanpa ID numerik -> teks penggunaan, tanpa mutasi.
    try:
        target_id = int(str(args[1]).strip())
    except (TypeError, ValueError):
        await update.effective_message.reply_text(MSG_SETUSER_USAGE)
        return

    if action == "add":
        users = user_store.add_user(users, target_id, _label_of(update, target_id))
        context.bot_data["users"] = users
        await _persist(settings, users)
        await update.effective_message.reply_text(MSG_SETUSER_ADDED.format(user_id=target_id))
        return

    # (4) remove: owner tidak bisa dihapus dari daftar efektif.
    if target_id == getattr(settings, "owner_user_id", None):
        await update.effective_message.reply_text(MSG_SETUSER_NEED_PRIVATE_OWNER)
        return

    users = user_store.remove_user(users, target_id)
    context.bot_data["users"] = users
    await _persist(settings, users)
    await update.effective_message.reply_text(MSG_SETUSER_REMOVED.format(user_id=target_id))


def _label_of(update, target_id: int) -> str:
    """Label tampilan: `"first_name (@username)"` bila target = pengirim, else kosong."""
    actor = getattr(update, "effective_user", None)
    if actor is None or getattr(actor, "id", None) != target_id:
        return ""
    first_name = getattr(actor, "first_name", "") or ""
    username = getattr(actor, "username", None)
    if username:
        return f"{first_name} (@{username})".strip()
    return str(first_name)


def _render_list(users: dict[int, str]) -> str:
    if not users:
        return MSG_SETUSER_LIST_EMPTY.format(total=0)
    lines = [MSG_SETUSER_LIST_HEADER.format(total=user_store.count(users))]
    for user_id in sorted(users):
        label = users[user_id]
        lines.append(f"- {user_id}" + (f" , {label}" if label else ""))
    return "\n".join(lines)


async def _persist(settings, users: dict[int, str]) -> bool:
    """Simpan atomik di thread terpisah; gagal -> log saja (handler tetap menjawab)."""
    return await asyncio.to_thread(user_store.save_users, settings.users_file, users)
