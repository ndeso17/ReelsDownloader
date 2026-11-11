# Package marker + re-export layanan URL (T-031).
# ALLOWED_HOSTS TIDAK di sini lagi: sumber kebenaran tunggal ada di validator.py (REWORK-R2).

from app.services.validator import (
    UnsupportedUrlError,
    detect_platform,
    extract_url,
    validate_url,
)

__all__ = [
    "validate_url",
    "extract_url",
    "detect_platform",
    "UnsupportedUrlError",
]
