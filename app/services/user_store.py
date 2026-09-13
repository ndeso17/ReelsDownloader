"""Store whitelist user (FR-014, SC 13): `dict[int, str]` di berkas JSON.

Kunci = Telegram user ID numerik, nilai = label tampilan `"first_name (@username)"`
untuk `/setUser list`. Serialisasi JSON memakai kunci string desimal supaya kompatibel
dengan semua klien (ID > 2^53 tidak dibulatkan oleh parser JSON pihak ketiga).

API murni sync/IO (AGENTS.md §4.2): pemanggil async membungkus dengan
`asyncio.to_thread`. Tidak ada dependensi baru; stdlib only.

Menyimpan (REWORK-R1, R2): `tempfile.mkstemp` di direktori target (nama tmp UNIK per
penulisan, mode 0600 sejak creation) -> isi -> `flush` -> `os.fsync(fd)` -> `chmod 0600`
eksplisit -> `os.replace` (atomik di volume yang sama) -> `fsync` direktori parent.
Tujuan: tidak ada tabrakan tmp antar penulis, mode file 0600 (bukan 0664 warisan umask),
dan rename bertahan crash/power loss.

Menyimpan aman dari balapan TIDAK cukup di sini: satu penulis saja yang boleh berada di
jalur baca-ubah-tulis pada satu berkas. Serialisasi transaksi itu hidup di lapisan
handler (`app/handlers/account.py::write_lock_for`, REWORK-R3).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

__all__ = ["add_user", "count", "load_users", "remove_user", "save_users"]

#: Mode berkas whitelist: 0600 (PRD/PLAN WP-15; whitelist = data akses, bukan publik).
FILE_MODE = 0o600


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


def _fsync_dir(directory: str) -> None:
    """`fsync` direktori parent supaya entri hasil `os.replace` ikut awet.

    Best effort: sebagian platform menolak `O_RDONLY` untuk direktori atau menolak
    `fsync` pada handle direktori; kasus itu tidak boleh menggagalkan penyimpanan.
    """
    try:
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        logger.debug("fsync direktori %s ditolak platform", directory)
    finally:
        os.close(dir_fd)


def _unlink_quietly(path: str) -> None:
    """Hapus tmp sisa kegagalan; abaikan bila sudah hilang."""
    try:
        os.unlink(path)
    except OSError:
        pass


def save_users(path: str | os.PathLike[str], users: dict[int, str]) -> bool:
    """Tulis atomik dan durable: tmp unik -> flush+fsync -> chmod 0600 -> replace -> fsync dir.

    Nama tmp dibuat `tempfile.mkstemp` di direktori target, jadi DUA pemanggilan
    serentak tidak pernah berbagi berkas tmp yang sama (akar penyebab file korup pada
    probe race QC). `mkstemp` mencipta berkas 0600 tanpa peduli umask; `chmod` eksplisit
    dipasang lagi sebelum `os.replace` supaya mode final 0600 selalu terbukti
    (REWORK-R1). Isi di-flush + `os.fsync` SEBELUM handle ditutup dan sebelum rename,
    lalu direktori parent ikut di-fsync agar entri rename awet (REWORK-R2).

    `OSError` -> `logger.error` + return `False` (TIDAK pernah raise): state in-memory
    tetap benar sampai restart, handler harus tetap menjawab. Bila gagal di tengah
    jalan, tmp dibersihkan (tidak ada `*.tmp` yatim).
    """
    target = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(target))
    payload = {str(user_id): label for user_id, label in users.items()}

    fd, tmp = -1, None
    try:
        # tmp Unik + 0600 sejak creation; fd mentah ditutup, tulis ulang lewat `open()`
        # agar pemanggilan tetap lewat seam `builtins.open` yang sudah diuji.
        fd, tmp = tempfile.mkstemp(prefix=f"{os.path.basename(target)}.", suffix=".tmp", dir=parent)
        os.close(fd)
        fd = -1
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            # Urutan PLAN 1492: tmp -> chmod 0600 -> fsync -> rename. `mkstemp` sudah
            # mencipta 0600; chmod ini membuat kontrak mode terbukti eksplisit di jalur
            # yang sama, dan terjadi SEBELUM rename sehingga tidak ada jendela 0644.
            os.chmod(tmp, FILE_MODE)
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        logger.error("gagal menyimpan users file %s: %s", target, exc)
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            _unlink_quietly(tmp)
        return False

    _fsync_dir(parent)
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
