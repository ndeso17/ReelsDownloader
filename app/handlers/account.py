"""Handler akun & akses + mode advance: `/getID` (FR-012), `/menu` (FR-016),
`/setUser` (FR-014), `/advance` + dialog inline (FR-015..FR-019), `/cancel` (FR-019).

`/getID` dan `/menu` PUBLIK di kedua mode (PRD §4). `/setUser` admin-only dan
hanya aktif di private mode. Guard `/setUser` berurutan dan TIDAK bisa dilewati:
tanpa guard, `/setUser` = penulisan daftar whitelist oleh siapa pun.
`/advance` digate `can_download` (FR-015:479 - user tidak terdaftar ditolak
FR-013; public mode tetap lolos semua).

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

from app.handlers.download import admit_advance_job
from app.services import advance as advance_service
from app.services import dialog as dialog_service
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
    can_download,
    is_owner,
    menu_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "advance_callback",
    "advance_command",
    "cancel_command",
    "get_id",
    "menu",
    "set_user",
    "stats",
    "write_lock_for",
]

#: T-165 (FR-020, SC 18): pemisah rincian alasan penolakan pada keluaran `/stats`.
_STATS_REASON_SEPARATOR = ", "

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


def _queue_line(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Baris kedalaman antrean `/stats` (FR-020, SC 18) dengan fallback WP-17.

    Antrean `asyncio.Queue` (FR-022) baru dibuat di WP-17, jadi `bot_data` belum
    tentu punya kunci `queue`: fallback PLAN T-165 dipakai selama itu, sehingga WP
    ini bisa diaudit tanpa menunggu WP-17. `qsize()` divaluasi dalam try/except
    agar objek pengganti yang tidak terduga tidak menggagalkan laporan.
    """
    queue = context.bot_data.get("queue")
    if queue is None:
        return "Antrean: n/a (belum diwiring)"
    try:
        depth = int(queue.qsize())
    except Exception:  # pragma: no cover - penjaga objek antrean tak terduga
        logger.warning("qsize() antrean tidak terbaca", exc_info=True)
        return "Antrean: n/a (belum diwiring)"
    max_size = getattr(context.bot_data["settings"], "queue_max_size", "?")
    return f"Antrean: {depth}/{max_size}"


def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Susun laporan `/stats` dari state statistik + antrean saat ini (SC 18).

    Kontrak persistensi = keputusan Executor di `app/services/stats.py` (lihat Log
    WP-16): `User unik` bertahan antar restart (dibaca dari `stats.json`), sedangkan
    `Diproses`/`Ditolak` adalah counter SEJAK RESTART. Label menyebut status itu
    eksplisit supaya angkanya tidak dibaca sebagai total sepanjang masa.
    """
    stats_service = context.bot_data.get("stats")
    if stats_service is None:
        # Jalur defensif (mis. test lama yang membangun bot_data manual).
        return "📊 Statistik belum tersedia."
    snap = stats_service.snapshot()
    reasons = snap["rejected_reasons"]
    detail = ", ".join(f"{key}={reasons[key]}" for key in sorted(reasons)) or "-"
    return (
        "📊 Statistik pemakaian\n"
        f"User unik: {snap['total_users']}\n"
        f"Diproses (sejak restart): {snap['processed']}\n"
        f"Ditolak (sejak restart): {snap['rejected']}\n"
        f"Rincian ditolak: {detail}\n"
        f"{_queue_line(context)}"
    )


async def stats(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """T-165 (FR-020, SC 18): `/stats` hanya untuk admin (`access.is_owner`).

    Guard mengikuti pola `/setUser`: selain owner -> `MSG_ACCESS_DENIED` standar,
    tanpa membocorkan ada/tidaknya statistik. Mode publik pun tetap terbatas
    (PRD FR-021: "di public mode tetap dibatasi ke admin").
    """
    settings = context.bot_data["settings"]
    if not is_owner(_user_id_of(update), settings):
        await update.effective_message.reply_text(MSG_ACCESS_DENIED)
        return
    await update.effective_message.reply_text(_stats_text(context))


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


# ============================ MODE ADVANCE (FR-015..FR-019) ============================


async def advance_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-015: `/advance` mengaktifkan mode advance per chat (in-memory).

    Gate = `can_download` (FR-015:479 - public mode lolos semua, private mode
    hanya user terdaftar). `/advance` kedua saat sesi aktif = toggle off
    (FR-015:477). BALASAN HANYA teks - keyboard baru muncul setelah URL valid
    masuk (FR-015:473 link-first, keputusan manusia 2026-09-14).
    """
    settings = context.bot_data["settings"]
    if not can_download(_user_id_of(update), settings, context.bot_data.get("users", {})):
        await update.effective_message.reply_text(MSG_ACCESS_DENIED)
        return
    dialog = context.bot_data.get("dialog")
    if dialog is None:
        # Defensif: startup tidak memasang dialog (mis. test lama) => skip diam-diam.
        return
    chat_id = update.effective_chat.id
    if dialog.active(chat_id):
        dialog.clear(chat_id)
        await update.effective_message.reply_text(dialog_service.MODE_OFF_TEXT)
        return
    dialog.set(chat_id, step=dialog_service.STEP_LINK)
    await update.effective_message.reply_text(dialog_service.MODE_TEXT)


async def cancel_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-019: `/cancel` membatalkan mode/dialog aktif + hapus state."""
    dialog = context.bot_data.get("dialog")
    if dialog is not None:
        dialog.clear(update.effective_chat.id)
    await update.effective_message.reply_text(dialog_service.CANCEL_MENU)


async def advance_callback(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-015..FR-019: router `ad:*` - `answer()` tepat sekali di SEMUA cabang
    (PRD §3: tidak boleh ada "Updating…" menggantung).

    Cabang (PLAN T-192): `ad:cancel` => clear + balas menu; sesi mati => toast
    `Sesi sudah berakhir` (+ `MSG_EXPIRED` bila tadinya ada tapi kedaluwarsa,
    PRD.md:542); `ad:mode:*` (step type) => simpan tipe + prompt kualitas;
    `ad:q:*`/`ad:a:*` (step quality, tipe cocok) => final: clear (satu sesi =
    satu link), recap, `url` dari state diantrekan ke worker WP-17; keyboard
    basi (step/tipe tidak cocok) => toast tanpa efek (FR-016).
    """
    query = update.callback_query
    dialog = context.bot_data.get("dialog")
    chat_id = update.effective_chat.id
    parsed = dialog_service.parse_callback(query.data or "")
    if parsed is None:
        # Format/data callback tidak dikenal: tidak sah (FR-016) -> toast basi.
        await query.answer(dialog_service.ANSWER_STALE)
        return
    kind, value = parsed
    if kind == "cancel":
        await query.answer()
        if dialog is not None:
            dialog.clear(chat_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(chat_id=chat_id, text=dialog_service.CANCEL_MENU)
        return
    expired = dialog is not None and dialog.is_expired(chat_id)
    state = dialog.get(chat_id) if dialog is not None else None
    if kind is None or state is None:
        await query.answer(dialog_service.ANSWER_STALE)
        if expired:
            await context.bot.send_message(chat_id=chat_id, text=dialog_service.MSG_EXPIRED)
        return
    if kind == "mode" and state.step == dialog_service.STEP_TYPE:
        dialog.set(chat_id, tipe=value, step=dialog_service.STEP_QUALITY)
        await query.answer()
        await query.edit_message_text(
            text=dialog_service.PROMPT_QUALITY,
            reply_markup=dialog_service.choice_keyboard(dialog_service.STEP_QUALITY, tipe=value),
        )
        return
    if state.step == dialog_service.STEP_QUALITY and kind in ("q", "a"):
        wanted = "video" if kind == "q" else "audio"
        if state.tipe != wanted or state.url is None:
            await query.answer(dialog_service.ANSWER_STALE)
            return
        updated = dialog.set(chat_id, kualitas=value)
        selection = advance_service.resolve_selection(updated)
        if selection is None:  # pragma: no cover - dijaga parse whitelist
            await query.answer(dialog_service.ANSWER_STALE)
            dialog.clear(chat_id)
            return
        dialog.clear(chat_id)  # sekali-pakai; mode auto-off (FR-015:478)
        await query.answer()
        label = (
            f"Video · {'Best' if value == 'best' else f'{value}p'}"
            if wanted == "video"
            else f"Audio · mp3 {value}k"
        )
        try:
            await query.edit_message_text(text=f"✅ Diproses: {label}")
        except Exception:
            # Pesan sumber sudah basi/dihapus client: recap bukan jalur kritis.
            logger.debug("recap edit_message_text gagal (chat %s)", chat_id, exc_info=True)
        await admit_advance_job(update, context, state.url, selection)
        return
    await query.answer(dialog_service.ANSWER_STALE)
