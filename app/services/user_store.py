"""Store whitelist user (FR-014, SC 13): `dict[int, str]` di berkas JSON.

Kunci = Telegram user ID numerik, nilai = label tampilan `"first_name (@username)"`
untuk `/setUser list`. Serialisasi JSON memakai kunci string desimal supaya kompatibel
dengan semua klien (ID > 2^53 tidak dibulatkan oleh parser JSON pihak ketiga).

API murni sync/IO (AGENTS.md §4.2): pemanggil async membungkus dengan
`asyncio.to_thread`. Tidak ada dependensi baru; stdlib only.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

__all__ = ["add_user", "count", "load_users", "remove_user", "save_users"]


def _as_int_key(key) -> int | None:
    """Kunci JSON string desimal -> int; selain itu None (diabaikan, tidak raise)."""
    try:
        return int(str(key).strip())
    except (TypeError, ValueError):
        return None


def load_users(path: str | os.PathLike[str]) -> dict[int, str]:
    """Baca whitelist dari `path`.

    Berkas hilang / rusak / JSON bukan object -> `{}` + `logger.warning`, TANPA
    raise: bot tetap hidup (mode private menjadi fail-closed lewat `access.py`).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.warning("users file %s tidak ada, mulai dengan daftar kosong", path)
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("users file %s tidak terbaca (%s), mulai dengan daftar kosong", path, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("users file %s bukan JSON object, mulai dengan daftar kosong", path)
        return {}

    users: dict[int, str] = {}
    for raw_key, raw_value in data.items():
        key = _as_int_key(raw_key)
        if key is None:
            logger.warning("kunci users %r bukan ID numerik, diabaikan", raw_key)
            continue
        users[key] = str(raw_value)
    return users


def save_users(path: str | os.PathLike[str], users: dict[int, str]) -> bool:
    """Tulis atomik: `path + ".tmp"` lalu `os.replace`.

    `OSError` -> `logger.error` + return `False` (TIDAK pernah raise): state
    in-memory tetap benar sampai restart, handler harus tetap menjawab.
    """
    tmp = os.fspath(path) + ".tmp"
    payload = {str(user_id): label for user_id, label in users.items()}
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        logger.error("gagal menyimpan users file %s: %s", path, exc)
        return False
    return True


def add_user(users: dict[int, str], user_id: int, label: str = "") -> dict[int, str]:
    """Masukkan/perbarui `user_id` pada salinan `users` (murni, tanpa mutate argumen)."""
    updated = dict(users)
    updated[int(user_id)] = label
    return updated


def remove_user(users: dict[int, str], user_id: int) -> dict[int, str]:
    """Hapus `user_id` bila ada; kembalikan salinan (tanpa mutate argumen)."""
    updated = dict(users)
    updated.pop(int(user_id), None)
    return updated


def count(users: dict[int, str]) -> int:
    """Jumlah user terdaftar."""
    return len(users)
