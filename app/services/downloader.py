"""yt-dlp downloader service (FR-005, FR-006).

Aturan yang mengikat modul ini (AGENTS.md):
- §2: yt-dlp lewat **Python API**, FFmpeg dipanggil yt-dlp (merge), bukan subprocess.
- §4.2: semua import top-level. §4.4: fungsi I/O `async def`, call blocking → `asyncio.to_thread`.
- §5: `outtmpl` tidak pernah memuat input user; nama file dihasilkan yt-dlp dari `%(id)s`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import Settings
from app.services.errors import (
    DownloadFailedError,
    FileTooLargeError,
    PrivateVideoError,
    VideoNotFoundError,
)

logger = logging.getLogger(__name__)

#: FR-006 — persis 6 field yang dibaca handler caption.
METADATA_FIELDS = ("title", "duration", "uploader", "webpage_url", "ext", "filesize")

#: NFR Reliability — hard-cap satu job download (T-046).
DOWNLOAD_TIMEOUT_SECONDS = 60


@dataclass
class DownloadResult:
    """Hasil download: path lokal + metadata 6 field."""

    path: Path
    metadata: dict


def extract_metadata(info: dict) -> dict:
    """Ambil 6 field FR-006; field yang hilang bernilai None."""
    return {field: info.get(field) for field in METADATA_FIELDS}


def build_ydl_opts(download_dir: str, max_bytes: int) -> dict:
    """Opts yt-dlp: format, merge mp4, outtmpl terkendali kode, timeout eksplisit.

    `max_bytes` dipasang ganda: pre-check manual di `_run_download` (T-044) dan
    `max_filesize` yt-dlp sebagai lantai kedua (T-042/T-044, FR-009).
    """
    opts: dict = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        # Nama file dihasilkan yt-dlp dari id — bukan input user (AGENTS.md §5).
        "outtmpl": os.path.join(download_dir, "%(id).10s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 0,
        "socket_timeout": 30,
        "http_timeout": 30,
        "restrict_fallback": False,
        "max_filesize": max_bytes,
    }
    return opts


#: Urutan sesuai PLAN T-045 (login/private/age lebih dulu). `age` pakai
#: word-boundary regex: substring mentah "age" ikut match di kata "Page not
#: found" dan menggeser VideoNotFoundError jadi PrivateVideoError (deviasi
#: tercatat di Log WP-04).
_PRIVATE_PATTERNS = re.compile(r"login|private|\bage\b|\bunderage\b", re.IGNORECASE)
_NOT_FOUND_PATTERNS = re.compile(r"not found|404|unavailable", re.IGNORECASE)


def _classify_yt_dlp_error(exc: yt_dlp.utils.YoutubeDLError) -> Exception:
    """Petakan pesan yt-dlp ke exception domain (T-045).

    `YoutubeDLError` = base class `DownloadError` DAN `ExtractorError` di
    yt-dlp 2026.8.19 (`issubclass(ExtractorError, DownloadError)` = False),
    jadi hanya base ini yang menangkap keduanya.
    """
    message = str(exc)
    if _PRIVATE_PATTERNS.search(message):
        return PrivateVideoError(message)
    if _NOT_FOUND_PATTERNS.search(message):
        return VideoNotFoundError(message)
    return DownloadFailedError(message)


def _run_download(url: str, opts: dict) -> DownloadResult:
    """Bagian blocking (Python API yt-dlp) — hanya dipanggil via asyncio.to_thread."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        # T-044: pre-check ukuran SEBELUM bit apa pun diunduh.
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise VideoNotFoundError(f"Ekstraksi metadata gagal untuk: {url}")

        filesize = info.get("filesize") or info.get("filesize_approx")
        max_bytes = opts["max_filesize"]
        if filesize is not None and filesize > max_bytes:
            raise FileTooLargeError(f"Ukuran video {filesize} byte melebihi batas {max_bytes} byte")

        downloaded = ydl.extract_info(url, download=True)
        if downloaded is None:
            raise DownloadFailedError(f"Download tidak menghasilkan info untuk: {url}")

        path = Path(ydl.prepare_filename(downloaded))
        if not path.exists():
            raise DownloadFailedError(f"File hasil download tidak ditemukan: {path}")

        return DownloadResult(path=path, metadata=extract_metadata(downloaded))


async def download(url: str, settings: Settings) -> DownloadResult:
    """Download satu URL IG/FB public, kembalikan path + metadata (FR-005, FR-006).

    Naik: `FileTooLargeError` (pre-check), `PrivateVideoError`,
    `VideoNotFoundError`, `DownloadFailedError`, atau `asyncio.TimeoutError`
    (hard-cap; dipetakan WP-10 ke pesan 'Timeout').
    """
    opts = build_ydl_opts(settings.download_dir, settings.max_file_size_mb * 1024 * 1024)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_download, url, opts),
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # asyncio.TimeoutError adalah alias TimeoutError di 3.12 — jangan diklasifikasi.
        logger.warning("Download job timeout >%ss: %s", DOWNLOAD_TIMEOUT_SECONDS, url)
        raise
    except yt_dlp.utils.YoutubeDLError as exc:
        raise _classify_yt_dlp_error(exc) from exc
