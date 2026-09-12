"""Satu-satunya rumah exception domain (T-041, WP-04).

Semua nama di modul ini dipakai ulang oleh WP-05/WP-08/WP-10 dan DILARANG
didefinisikan ulang di modul lain. Semuanya subclass ``Exception`` langsung —
bukan bertingkat — supaya `except DownloadFailedError` tidak diam-diam
menangkap varian spesifik.
"""

from __future__ import annotations


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
