"""Satu-satunya rumah exception domain (T-041, WP-04).

Semua nama di modul ini dipakai ulang oleh WP-05/WP-08/WP-10 dan DILARANG
didefinisikan ulang di modul lain. Semuanya subclass ``Exception`` langsung
bukan bertingkat, supaya `except DownloadFailedError` tidak diam-diam
menangkap varian spesifik.
"""

from __future__ import annotations

from app.services.validator import UnsupportedUrlError


class DownloadFailedError(Exception):
    """Download gagal karena alasan yang tidak terklasifikasi."""


class PrivateVideoError(Exception):
    """Video privat / butuh login / age-restricted (FR-009 #4)."""


class VideoNotFoundError(Exception):
    """Video tidak ditemukan / sudah dihapus (FR-009 #3)."""


class FileTooLargeError(Exception):
    """Ukuran melebihi MAX_FILE_SIZE_MB (FR-009 #5)."""


class FFmpegFailedError(Exception):
    """Proses FFmpeg (merge/konversi) gagal (FR-009 #8)."""


class UploadError(Exception):
    """Upload ke Telegram gagal (WP-05)."""


class NetworkError(Exception):
    """Koneksi jaringan gagal (WP-05/WP-10)."""


class RateLimitedError(Exception):
    """Request ditolak: user mengirim lagi sebelum ``rate_limit_seconds`` lewat (FR-011).

    ``retry_after`` = detik tersisa sampai user boleh mengirim lagi; dipakai
    handler WP-06 untuk pesan "tunggu N detik".
    """

    retry_after: float

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Terlalu sering; coba lagi dalam {retry_after:.1f} detik")
        self.retry_after = float(retry_after)


# ---------------------------------------------------------------------------
# T-101 (WP-10, FR-009): mapping exception -> pesan user-facing.
#
# Nama exception pada PLAN T-101 (`FileSizeExceededError`, `RateLimitError`,
# `FfmpegFailedError`, `TimeoutErrorUser`) tidak didefinisikan ulang di sini:
# docstring modul ini + AGENTS.md §4.2 mewajibkan satu rumah nama, dan kelas
# WP-04/WP-05 (`FileTooLargeError`, `RateLimitedError`, `FFmpegFailedError`)
# sudah dipakai `downloader.py`/`uploader.py`/`rate_limiter.py`: file yang
# bukan bagian daftar File WP-10. Pemetaan tetap satu-persatu ke 9 kondisi
# PRD §9; `TimeoutErrorUser` (opsional di PLAN) tidak dibuat karena
# `asyncio.TimeoutError` = `TimeoutError` di Python 3.12 dan sudah naik apa
# adanya dari `downloader.download` (lihat test_downloader.py T-046).
# ---------------------------------------------------------------------------

#: FR-009 #2: URL di luar whitelist Instagram/Facebook/YouTube.
MSG_URL_UNSUPPORTED = "❌ URL tidak didukung. Kirim link Instagram/Facebook/YouTube."

#: FR-009 #1: URL tidak bisa diparse / bukan URL.
MSG_URL_INVALID = "❌ URL tidak valid"

#: FR-009 #4: privat / butuh login / age-restricted.
MSG_PRIVATE = "🔒 Video private/terbatas."

#: FR-009 #3: tidak ditemukan / sudah dihapus.
MSG_NOT_FOUND = "🔍 Video tidak ditemukan."

#: FR-009 #6: gagal unduh yang tidak terklasifikasi.
MSG_DOWNLOAD_FAILED = "⚠️ Gagal mengunduh."

#: FR-009 #7: FFmpeg merge/konversi gagal.
MSG_FFMPEG_FAILED = "⚠️ Gagal memproses video."

#: FR-009 #8: melebihi MAX_FILE_SIZE_MB.
MSG_FILE_TOO_LARGE = "📏 File terlalu besar."

#: FR-009 #9: upload Telegram gagal.
MSG_UPLOAD_FAILED = "⚠️ Gagal mengirim ke Telegram."

#: FR-009 #9 (kondisi 9): hard-cap waktu terlampaui.
MSG_TIMEOUT = "⏱️ Timeout."

#: Jaringan: di luar 9 kondisi PRD §9, tapi punya exception domain sendiri.
MSG_NETWORK_FAILED = "⚠️ Gagal terhubung ke internet. Coba lagi."

#: Jaring terakhir: T-103: pesan apa pun harus bersih, tanpa isi exception.
MSG_GENERIC = "⚠️ Terjadi kesalahan. Coba lagi sebentar lagi."


def user_message(exc: Exception) -> str:
    """Pesan ramah user untuk satu exception (FR-009, T-101).

    Pemetaan eksplisit per kelas, berurutan; bukan `str(exc)` supaya detail
    internal (pesan yt-dlp, path, traceback) tidak pernah sampai ke chat
    AGENTS.md §5: traceback lengkap hanya ke log. Exception tak dikenal jatuh
    ke `MSG_GENERIC`.
    """
    # Urutan penting: kelas-kelas ini bersaudara langsung (bukan hierarki),
    # jadi tidak ada risiko salah tangkap antar domain, tapi ValueError dan
    # TimeoutError adalah builtins yang bisa menaungi banyak hal → paling akhir.
    if isinstance(exc, UnsupportedUrlError):
        return MSG_URL_UNSUPPORTED
    if isinstance(exc, RateLimitedError):
        return f"⏳ Terlalu sering; coba lagi dalam {exc.retry_after:.0f} detik"
    if isinstance(exc, PrivateVideoError):
        return MSG_PRIVATE
    if isinstance(exc, VideoNotFoundError):
        return MSG_NOT_FOUND
    if isinstance(exc, FileTooLargeError):
        return MSG_FILE_TOO_LARGE
    if isinstance(exc, FFmpegFailedError):
        return MSG_FFMPEG_FAILED
    if isinstance(exc, UploadError):
        return MSG_UPLOAD_FAILED
    if isinstance(exc, NetworkError):
        return MSG_NETWORK_FAILED
    if isinstance(exc, DownloadFailedError):
        return MSG_DOWNLOAD_FAILED
    if isinstance(exc, TimeoutError):
        return MSG_TIMEOUT
    if isinstance(exc, ValueError):
        return MSG_URL_INVALID
    return MSG_GENERIC
