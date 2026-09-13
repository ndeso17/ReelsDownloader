"""Utilitas file (FR-008): sanitisasi nama, pembersihan direktori, scrub metadata.

Fungsi di modul ini sinkron dan murni (atau I/O lokal ringan). Pemanggil di jalur
request handler wajib membungkus ``clean_dir`` dengan ``asyncio.to_thread`` sesuai
AGENTS.md §4.4, pola yang sama dengan ``_run_download`` di WP-04.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Blacklist WP-07. T-072 menulis `/ : \\ * ? " < > |` dan T-073 menulis set yang sama;
# `:` ikut diganti `_` karena assert verbatim T-073 hanya terpenuhi untuk set itu.
# Spasi BUKAN char berbahaya -> dipertahankan (ditegaskan ulang di T-073).
_UNSAFE_RE = re.compile(r'[/:\\*?"<>|]')

# Control char ASCII (NUL, SOH, tab, newline, dst.) + DEL.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_MAX_NAME_LEN = 100
_MAX_FIELD_LEN = 100


def sanitize_filename(name: str) -> str:
    """Ganti karakter berbahaya dengan ``_`` lalu truncate sampai 100 char."""
    return _UNSAFE_RE.sub("_", name)[:_MAX_NAME_LEN]


def clean_dir(directory: Path) -> None:
    """Hapus semua file di dalam *directory* (T-072: "hapus semua file di dir").

    Symlink ikut dihapus (ia entri file, bukan direktori). Subdirektori sengaja
    TIDAK dihapus recursively: di luar frasa "semua file" dan di luar scope WP-07
    (AGENTS.md §3.2 langkah 3, tanpa fitur tambahan). Alur download hanya
    menaruh file di `downloads/`, jadi T-074 dan assert cleanup WP-09
    (`iterdir() == []`) tetap terpenuhi. Direktori yang tidak ada dianggap sudah
    bersih, jadi fungsi ini tidak raise untuk path absen.
    """
    if not directory.is_dir():
        return
    for child in directory.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()


def sanitize_metadata(meta: dict) -> dict:
    """Strip control chars lalu truncate tiap field string sampai 100 char.

    Kunci dan nilai non-string (int/float/bool/None) dilewatkan apa adanya.
    """
    cleaned: dict = {}
    for key, value in meta.items():
        if isinstance(value, str):
            cleaned[key] = _CONTROL_RE.sub("", value)[:_MAX_FIELD_LEN]
        else:
            cleaned[key] = value
    return cleaned


def safe_remove(path: Path) -> None:
    """Hapus satu file bila ada (T-091, FR-008).

    ``FileNotFoundError`` dianggap sukses (file sudah hilang = tujuan tercapai),
    sehingga cleanup idempoten: aman dipanggil dua kali atau untuk path yang
    sudah dihapus proses lain. ``OSError`` lain (mis. permission) tetap naik
    kegagalan nyata tidak boleh disembunyikan.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return


def ensure_clean_dir(directory: Path, max_age_seconds: float = 86400) -> None:
    """Hapus file di *directory* yang lebih tua dari *max_age_seconds* (T-092, FR-008).

    Default 1 hari. File baru tidak disentuh; subdirektori dilewati (hanya
    "file" yang jadi scope cleanup). Path absen = tidak ada kerja.
    """
    if not directory.is_dir():
        return
    now = time.time()
    for child in directory.iterdir():
        if child.is_file():
            try:
                age = now - child.stat().st_mtime
            except FileNotFoundError:
                # Race: file hilang antara iterdir() dan stat(): sudah bersih.
                continue
            if age > max_age_seconds:
                safe_remove(child)
