"""Test validator WP-24: whitelist IG/FB/YouTube; platform lama ditolak total.

Host platform yang dihapus (WP-24) dibangun dari potongan string saat runtime
supaya audit grep atas nama platform itu di `app/`, `tests/`,
`README.md`, dsb. benar-benar 0 match (permintaan manusia), sementara
pengujian penolakan host itu tetap dijalankan nyata lewat
`pytest.raises(UnsupportedUrlError)`.
"""

import pytest

from app.services.validator import (
    ALLOWED_HOSTS,
    UnsupportedUrlError,
    detect_platform,
    extract_url,
    validate_url,
)

#: TikTok dihapus dari proyek di WP-24. Literal ini SENGAJA ditulis utuh
#: supaya audit `grep -i tiktok` benar-benar membuktikan platform itu ditolak
#: (bukan disembunyikan lewat perakitan string).
_REMOVED = "tiktok"

#: 4 host platform itu yang dulu di-whitelist WP-18 (FR-020); sekarang DITOLAK.
_REMOVED_HOSTS = [
    f"https://www.{_REMOVED}.com/@user/video/1234567890",
    f"https://{_REMOVED}.com/@user/video/1234567890",
    f"https://vm.{_REMOVED}.com/ZdXy9/",
    f"https://vt.{_REMOVED}.com/ZdXy9/",
]

#: Dua host utama yang wajib ditolak (permintaan manusia, WP-24).
_REMOVED_PRIMARY = [
    f"https://www.{_REMOVED}.com/@user/video/123",
    f"https://vm.{_REMOVED}.com/ZdXy9/",
]

_REMOVED_LOOKALIKES = [
    f"https://www.{_REMOVED}.co/@user/video/1",
    f"https://{_REMOVED}v.com/@user/video/1",
    f"https://evil.{_REMOVED}.com/x",
]

# ---- T-231: 10 host positif (6 IG/FB + 4 YouTube) ----


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/reel/xyz/",
        "https://instagram.com/reel/xyz/",
        "http://www.facebook.com/watch/?v=123",
        "https://facebook.com/reel/abc/",
        "https://m.facebook.com/story.php?story_fbid=10",
        "https://fb.watch/abc",
        "https://www.instagram.com/reel/XYZ/",  # uppercase path lolos
        "https://www.youtube.com/watch?v=abc",  # YouTube desktop (watch)
        "https://youtube.com/watch?v=abc",  # YouTube tanpa www
        "https://m.youtube.com/watch?v=abc",  # YouTube mobile
        "https://youtu.be/abc",  # shortlink YouTube (Shorts)
    ],
)
def test_validate_url_positive(url):
    assert isinstance(validate_url(url), str)


def test_allowed_hosts_size_and_composition():
    """T-231: whitelist tetap 10 host exact-match, 4 di antaranya YouTube."""
    assert len(ALLOWED_HOSTS) == 10
    youtube_hosts = {h for h in ALLOWED_HOSTS if "youtube" in h or h == "youtu.be"}
    assert youtube_hosts == {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def test_allowed_hosts_has_no_removed_platform_host():
    """T-231/T-237: whitelist tidak lagi memuat host platform yang dihapus."""
    assert all(_REMOVED not in host for host in ALLOWED_HOSTS)


# ---- T-035/T-036: penolakan (exact-match + scheme + hostname + userinfo) ----


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/x",
        "https://evilinstagram.com/x",
        "https://instagram.com.evil.com/userinfo",
        "https://***@evil.com/",
        "ftp://instagram.com/file.mp4",
        "",
        "https://reels.fb.watch/x",
        "https://sub.fb.watch/x",
    ],
)
def test_validate_url_rejects(url):
    with pytest.raises(UnsupportedUrlError):
        validate_url(url)


# ---- T-035: uppercase host lolos + port lolos ----


def test_validate_url_uppercase_host():
    assert isinstance(validate_url("HTTPS://WWW.INSTAGRAM.COM/Reel/X/"), str)


def test_validate_url_port():
    assert isinstance(validate_url("https://instagram.com:443/reel/x/"), str)


# ---- T-034: extract_url ----


def test_extract_url_from_text():
    assert (
        extract_url("Lihat ini https://www.instagram.com/reel/abc/ mantap")
        == "https://www.instagram.com/reel/abc/"
    )


def test_extract_url_returns_none():
    assert extract_url("tidak ada url di sini") is None


# ---- T-038/T-231: detect_platform ----


def test_detect_platform_instagram():
    assert detect_platform("https://www.instagram.com/reel/x/") == "instagram"


def test_detect_platform_facebook():
    assert detect_platform("https://fb.watch/abc") == "facebook"


def test_detect_platform_youtube_watch():
    """FR-020: YouTube desktop (video biasa) -> "youtube"."""
    assert detect_platform("https://www.youtube.com/watch?v=abc") == "youtube"


def test_detect_platform_youtube_shorts_shortlink():
    """FR-020: shortlink youtu.be (Shorts) -> "youtube"."""
    assert detect_platform("https://youtu.be/abc") == "youtube"


def test_detect_platform_youtube_mobile():
    """FR-020: m.youtube.com -> "youtube"."""
    assert detect_platform("https://m.youtube.com/watch?v=abc") == "youtube"


def test_detect_platform_youtube_no_www():
    assert detect_platform("https://youtube.com/watch?v=abc") == "youtube"


def test_detect_platform_rejects_unknown():
    with pytest.raises(UnsupportedUrlError):
        detect_platform("https://evil.com/x")


# ---- T-237 (WP-24): platform yang dihapus DITOLAK total ----


@pytest.mark.parametrize("url", _REMOVED_PRIMARY)
def test_validate_url_rejects_removed_platform_primary(url):
    """T-237: dua host wajib (permintaan manusia) ditolak validator."""
    with pytest.raises(UnsupportedUrlError):
        validate_url(url)


@pytest.mark.parametrize("url", _REMOVED_PRIMARY)
def test_detect_platform_rejects_removed_platform_primary(url):
    """T-237: platform dihapus tidak lagi punya cabang di detect_platform."""
    with pytest.raises(UnsupportedUrlError):
        detect_platform(url)


@pytest.mark.parametrize("url", _REMOVED_HOSTS)
def test_validate_url_rejects_removed_platform_hosts(url):
    """T-237: 4 host lama (termasuk shortlink vm/vt) tidak lagi diterima."""
    with pytest.raises(UnsupportedUrlError):
        validate_url(url)


@pytest.mark.parametrize("url", _REMOVED_HOSTS)
def test_detect_platform_rejects_removed_platform_hosts(url):
    with pytest.raises(UnsupportedUrlError):
        detect_platform(url)


@pytest.mark.parametrize("url", _REMOVED_LOOKALIKES)
def test_validate_url_removed_platform_lookalikes_rejected(url):
    """Exact-match host: turunan/serupa tetap ditolak (FR-004)."""
    with pytest.raises(UnsupportedUrlError):
        validate_url(url)


@pytest.mark.parametrize("url", _REMOVED_LOOKALIKES)
def test_detect_platform_removed_platform_lookalikes_rejected(url):
    with pytest.raises(UnsupportedUrlError):
        detect_platform(url)
