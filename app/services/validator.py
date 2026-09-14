"""URL validator + platform detection untuk Instagram / Facebook / TikTok (FR-003, FR-004, FR-020).

Sumber kebenaran ALLOWED_HOSTS: level modul, 10 host (6 lama + 4 TikTok,
termasuk shortlink `vt`/`vm`), exact-match.
Import top-level (AGENTS.md §4.2).
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "m.facebook.com",
    "tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "www.facebook.com",
    "www.instagram.com",
    "www.tiktok.com",
}


class UnsupportedUrlError(Exception):
    """URL bukan Instagram/Facebook/TikTok."""


def extract_url(text: str) -> str | None:
    """Ambil URL https/https pertama dari teks berbalut (FR-003)."""
    match = re.search(r"https?://\S+", text)
    if match:
        return match.group(0)
    return None


def validate_url(url: str) -> str:
    """Validasi URL: hanya Instagram/Facebook/TikTok exact-match.

    Mengembalikan URL ternormalisasi (scheme + hostname lowercase + komponen
    lain) bila valid. Menaikkan UnsupportedUrlError untuk host/scheme/kosong.
    """
    parsed = urlparse(url)

    if not parsed.scheme or parsed.scheme.lower() not in ("http", "https"):
        raise UnsupportedUrlError(f"Scheme tidak didukung: '{parsed.scheme}'")

    if not parsed.hostname:
        raise UnsupportedUrlError("Hostname kosong")

    host = parsed.hostname.lower()

    if host not in ALLOWED_HOSTS:
        raise UnsupportedUrlError(f"Host tidak didukung: '{host}'")

    netloc = host
    if parsed.port:
        netloc += f":{parsed.port}"
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        netloc = f"{auth}@{netloc}"

    return (
        f"{parsed.scheme.lower()}://{netloc}{parsed.path}"
        + (f";{parsed.params}" if parsed.params else "")
        + (f"?{parsed.query}" if parsed.query else "")
        + (f"#{parsed.fragment}" if parsed.fragment else "")
    )


def detect_platform(url: str) -> Literal["instagram", "facebook", "tiktok"]:
    """Deteksi platform dari hostname (FR-003/FR-007/FR-020)."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise UnsupportedUrlError("Hostname kosong")

    host = parsed.hostname.lower()

    if host in {"instagram.com", "www.instagram.com"}:
        return "instagram"

    if host in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"}:
        return "facebook"

    if host in {"www.tiktok.com", "tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        return "tiktok"

    raise UnsupportedUrlError(f"Host tidak didukung: '{host}'")
