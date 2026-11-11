"""Lapisan akses whitelist (FR-013, FR-015, FR-016): mode public/private.

Satu rumah untuk keputusan akses DAN konstanta pesan akses (AGENTS.md §4.2):
handler hanya memanggil, tidak menduplikasi logika atau teks.

Perbandingan SELALU user ID numerik (int), bukan username (PRD §4 Security):
username bisa berubah dan bisa dipalsukan; ID tidak.

`can_download` SELALU True saat `bot_mode="public"` sehingga perilaku v1.0
(dan 206 test lama) tidak berubah. Saat private: hanya daftar efektif
(union owner + seed env + kunci users file). Daftar efektif kosong ->
fail-closed: semua permintaan download ditolak.
"""

from __future__ import annotations

import logging

from app.services.user_store import count as user_count

logger = logging.getLogger(__name__)

__all__ = [
    "MSG_ACCESS_DENIED",
    "MSG_GETID",
    "MSG_SETUSER_ADDED",
    "MSG_SETUSER_INACTIVE",
    "MSG_SETUSER_LIST_HEADER",
    "MSG_SETUSER_LIST_EMPTY",
    "MSG_SETUSER_NEED_PRIVATE_OWNER",
    "MSG_SETUSER_REMOVED",
    "MSG_SETUSER_USAGE",
    "can_download",
    "effective_ids",
    "is_owner",
    "menu_text",
]

#: Pesan penolakan akses standar (FR-013; teks dikunci kontrak WP-15 T-153).
MSG_ACCESS_DENIED = "🚫 Akses ditolak. Bot hanya untuk pengguna terdaftar."
MSG_GETID = "🆔 Telegram ID kamu: {user_id}"
MSG_SETUSER_INACTIVE = "i️ /setUser tidak aktif dalam mode public."
MSG_SETUSER_USAGE = (
    "Cara pakai:\n"
    "/setUser add <telegram_id>\n"
    "/setUser remove <telegram_id>\n"
    "/setUser list\n"
    "ID harus angka (lihat /getID)."
)
MSG_SETUSER_ADDED = "✅ User {user_id} ditambahkan ke daftar akses."
MSG_SETUSER_REMOVED = "✅ User {user_id} dihapus dari daftar akses."
MSG_SETUSER_LIST_HEADER = "👥 {total} user terdaftar:\n"
MSG_SETUSER_LIST_EMPTY = "👥 Belum ada user terdaftar selain owner. Daftar akses: {total}."
MSG_SETUSER_NEED_PRIVATE_OWNER = (
    "🚫 Owner tidak bisa dihapus dari daftar akses. Ubah OWNER_USER_ID di .env."
)


def _bot_mode(settings) -> str:
    """`bot_mode` dengan fallback publik.

    `getattr` dibutuhkan karena test lama membangun Settings via
    `model_construct()` (tanpa field v2.2); hanya nilai literal `"private"`
    yang mengaktifkan gate, selain itu dianggap `public` (perilaku v1.0).
    """
    return "private" if getattr(settings, "bot_mode", None) == "private" else "public"


def effective_ids(settings, users: dict[int, str]) -> frozenset[int]:
    """Daftar efektif = union(owner, seed env AUTHORIZED_USER_IDS, kunci users file)."""
    ids: set[int] = set()
    owner = getattr(settings, "owner_user_id", None)
    if owner is not None:
        ids.add(int(owner))
    parser = getattr(settings, "authorized_ids_set", None)
    if callable(parser):
        seed_ids = parser()
        if isinstance(seed_ids, frozenset):
            ids.update(seed_ids)
    ids.update(int(key) for key in users)
    return frozenset(ids)


def is_owner(user_id, settings) -> bool:
    """True hanya bila `user_id` numerik sama dengan `OWNER_USER_ID` (bukan username)."""
    if user_id is None:
        return False
    owner = getattr(settings, "owner_user_id", None)
    if owner is None:
        return False
    try:
        return int(user_id) == int(owner)
    except (TypeError, ValueError):
        return False


def can_download(user_id, settings, users: dict[int, str]) -> bool:
    """Gerbang FR-013/FR-015: publik -> selalu True; private -> hanya daftar efektif."""
    if _bot_mode(settings) == "public":
        return True
    if user_id is None:
        return False
    return int(user_id) in effective_ids(settings, users)


def menu_text(settings, user_id, users: dict[int, str]) -> str:
    """Teks `/menu` (FR-016): daftar command v2.2 + status akses pengirim."""
    if _bot_mode(settings) == "public":
        status = "Publik"
    elif user_id is not None and int(user_id) in effective_ids(settings, users):
        status = "Terdaftar"
    else:
        status = "Tidak terdaftar"
    total = user_count(users)
    return (
        "📋 Menu\n"
        "/getID  , lihat Telegram ID kamu (publik)\n"
        "/start  , selamat datang + menu (publik)\n"
        "/menu   , daftar ini (publik)\n"
        "/advance, download dengan dialog pilihan (user terdaftar)\n"
        "/setUser, kelola user (admin)\n"
        "/cancel , batalkan dialog aktif (user terdaftar)\n"
        "/stats  , statistik pemakaian (admin)\n"
        "\n"
        f"Status akses Anda: {status}\n"
        f"User terdaftar: {total}"
    )
