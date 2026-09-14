import pytest

from app.services.validator import (
    UnsupportedUrlError,
    detect_platform,
    extract_url,
    validate_url,
)

# ---- T-035/T-036: 6 host positif ----


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
    ],
)
def test_validate_url_positive(url):
    assert isinstance(validate_url(url), str)


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


# ---- T-038: detect_platform ----


def test_detect_platform_instagram():
    assert detect_platform("https://www.instagram.com/reel/x/") == "instagram"


def test_detect_platform_facebook():
    assert detect_platform("https://fb.watch/abc") == "facebook"


def test_detect_platform_rejects_unknown():
    with pytest.raises(UnsupportedUrlError):
        detect_platform("https://evil.com/x")


# ---- T-181/T-184: TikTok (FR-020) ----

TIKTOK_HOSTS = [
    "https://www.tiktok.com/@user/video/1234567890",
    "https://tiktok.com/@user/video/1234567890",
    "https://vm.tiktok.com/ZdXy9/",
    "https://vt.tiktok.com/ZdXy9/",
]


@pytest.mark.parametrize("url", TIKTOK_HOSTS)
def test_validate_url_tiktok_accepted(url):
    assert isinstance(validate_url(url), str)


@pytest.mark.parametrize("url", TIKTOK_HOSTS)
def test_detect_platform_tiktok(url):
    assert detect_platform(url) == "tiktok"


def test_validate_url_tiktok_shortlink_passthrough():
    """Shortlink vm/vt diterima apa adanya (FR-020) - yt-dlp yang resolve."""
    normalized = validate_url("https://vm.tiktok.com/ZdXy9/")
    assert normalized == "https://vm.tiktok.com/ZdXy9/"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.co/@user/video/1",
        "https://tiktokv.com/@user/video/1",
        "https://tiktok.example.com/evil",
        "https://example-tiktok.com/x",
        "https://evil.tiktok.com/x",
    ],
)
def test_validate_url_tiktok_lookalikes_rejected(url):
    """Exact-match host: turunan/serupa tetap ditolak (FR-004)."""
    with pytest.raises(UnsupportedUrlError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.co/@user/video/1",
        "https://tiktokv.com/@user/video/1",
        "https://evil.tiktok.com/x",
    ],
)
def test_detect_platform_tiktok_lookalikes_rejected(url):
    with pytest.raises(UnsupportedUrlError):
        detect_platform(url)
