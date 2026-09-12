"""Test downloader WP-04 (T-047) — tanpa network (AGENTS.md §4.6).

Semua akses yt-dlp lewat `MockYDL` dari fixture `mock_ydl` (tests/conftest.py).
Catatan: pytest me-load `tests/conftest.py` sebagai module top-level `conftest`,
jadi JANGAN `from tests.conftest import MockYDL` — itu objek kelas berbeda dan
mutasi padanya tidak terlihat oleh kelas yang dipatch. Selalu pakai kelas yang
dikembalikan fixture.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, YoutubeDLError

from app.config import Settings
from app.services import downloader as downloader_mod
from app.services.downloader import (
    DOWNLOAD_TIMEOUT_SECONDS,
    METADATA_FIELDS,
    DownloadResult,
    build_ydl_opts,
    download,
    extract_metadata,
)
from app.services.errors import (
    DownloadFailedError,
    FFmpegFailedError,
    FileTooLargeError,
    NetworkError,
    PrivateVideoError,
    UploadError,
    VideoNotFoundError,
)

MAX_50MB = 50 * 1024 * 1024
FAKE_URL = "https://example.test/reel/ABC123"

FULL_INFO = {
    "id": "ABC123",
    "title": "Reels sunset",
    "duration": 42,
    "uploader": "creator",
    "webpage_url": FAKE_URL,
    "ext": "mp4",
    "filesize": 8_000_000,
}


@pytest.fixture
def settings(tmp_downloads: str) -> Settings:
    """Settings instance terisolasi: download_dir → tmp_downloads, limit 50 MB."""
    dummy_token = " ".join(["dummy", "token"])  # bukan kredensial; hindari literal token
    return Settings.model_construct(
        telegram_bot_token=dummy_token,
        log_level="INFO",
        download_dir=tmp_downloads,
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_window_seconds=10,
    )


def _make_output(tmp_downloads: str, name: str = "ABC123.mp4") -> Path:
    """Simulasikan file hasil unduhan agar path.exists() lolos."""
    path = Path(tmp_downloads) / name
    path.write_bytes(b"fake-video-bytes")
    return path


# ---------------- errors.py (T-041) ----------------


@pytest.mark.parametrize(
    "cls",
    [
        DownloadFailedError,
        PrivateVideoError,
        VideoNotFoundError,
        FileTooLargeError,
        FFmpegFailedError,
        UploadError,
        NetworkError,
    ],
)
def test_domain_errors_are_exception_subclasses(cls):
    assert issubclass(cls, Exception)


def test_domain_errors_are_flat_not_nested():
    """Varian spesifik bukan subclass DownloadFailedError (kontrak: 7 Exception sibling)."""
    assert not issubclass(VideoNotFoundError, DownloadFailedError)
    assert not issubclass(FileTooLargeError, DownloadFailedError)
    assert not issubclass(PrivateVideoError, DownloadFailedError)


def test_errors_module_is_only_home_of_domain_exceptions():
    """Modul lain dilarang mendefinisikan ulang nama exception domain."""
    import app.services.validator as validator_mod

    assert not hasattr(validator_mod, "DownloadFailedError")
    assert not hasattr(validator_mod, "VideoNotFoundError")


# ---------------- extract_metadata (T-041, FR-006) ----------------


def test_metadata_fields_exact_prd_six():
    assert METADATA_FIELDS == ("title", "duration", "uploader", "webpage_url", "ext", "filesize")


def test_extract_metadata_returns_six_fields():
    meta = extract_metadata(FULL_INFO)
    assert set(meta) == set(METADATA_FIELDS)
    assert meta["title"] == "Reels sunset"
    assert meta["duration"] == 42
    assert meta["uploader"] == "creator"
    assert meta["webpage_url"] == FAKE_URL
    assert meta["ext"] == "mp4"
    assert meta["filesize"] == 8_000_000


def test_extract_metadata_missing_fields_become_none():
    meta = extract_metadata({"title": "Test", "duration": 120})
    assert meta["title"] == "Test"
    assert meta["duration"] == 120
    for field in ("uploader", "webpage_url", "ext", "filesize"):
        assert meta[field] is None


def test_extract_metadata_empty_info():
    assert set(extract_metadata({})) == set(METADATA_FIELDS)


def test_download_result_dataclass_fields(tmp_path: Path):
    result = DownloadResult(path=tmp_path / "x.mp4", metadata={"title": "T"})
    assert result.path == tmp_path / "x.mp4"
    assert result.metadata == {"title": "T"}


# ---------------- build_ydl_opts (T-042, T-046) ----------------


def test_build_ydl_opts_format_and_merge(tmp_downloads: str):
    opts = build_ydl_opts(tmp_downloads, MAX_50MB)
    assert opts["format"] == "bestvideo+bestaudio/best"
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert opts["quiet"] is True
    assert opts["no_warnings"] is True


def test_build_ydl_opts_outtmpl_code_controlled_no_title(tmp_downloads: str):
    """outtmpl = join(dir, '%(id).10s.%(ext)s') — TANPA input user, TANPA %(title)s."""
    opts = build_ydl_opts(tmp_downloads, MAX_50MB)
    assert opts["outtmpl"] == os.path.join(tmp_downloads, "%(id).10s.%(ext)s")
    assert "%(title)" not in opts["outtmpl"]


def test_build_ydl_opts_timeout_keys(tmp_downloads: str):
    opts = build_ydl_opts(tmp_downloads, MAX_50MB)
    for key in ("socket_timeout", "http_timeout", "retries", "restrict_fallback"):
        assert key in opts, key
    assert opts["socket_timeout"] == 30
    assert opts["http_timeout"] == 30
    assert opts["retries"] == 0
    assert opts["restrict_fallback"] is False


def test_build_ydl_opts_max_filesize(tmp_downloads: str):
    assert build_ydl_opts(tmp_downloads, MAX_50MB)["max_filesize"] == MAX_50MB


def test_build_ydl_opts_accepted_by_real_youtube_dl(tmp_downloads: str):
    """T-046: YoutubeDL asli menerima opts & menyimpan param itu — tanpa network."""
    params = yt_dlp.YoutubeDL(build_ydl_opts(tmp_downloads, MAX_50MB)).params
    for key in (
        "format",
        "merge_output_format",
        "outtmpl",
        "noplaylist",
        "quiet",
        "socket_timeout",
        "http_timeout",
        "retries",
        "restrict_fallback",
        "max_filesize",
    ):
        assert key in params, key
    assert params["socket_timeout"] == 30
    assert params["http_timeout"] == 30
    assert params["retries"] == 0
    assert params["restrict_fallback"] is False
    assert params["max_filesize"] == MAX_50MB


# ---------------- download happy path (T-043, T-047) ----------------


async def test_download_happy_path(mock_ydl: type, settings: Settings, tmp_downloads: str):
    mock_ydl.info = dict(FULL_INFO)
    expected = _make_output(tmp_downloads)

    result = await download(FAKE_URL, settings)

    assert isinstance(result, DownloadResult)
    assert result.path == expected
    assert result.metadata == extract_metadata(FULL_INFO)
    # pre-check (download=False) selalu sebelum unduhan (download=True)
    flags = [call["download"] for inst in mock_ydl.instances for call in inst.calls]
    assert flags == [False, True]


async def test_download_uses_worker_thread_not_event_loop(
    mock_ydl: type, settings: Settings, tmp_downloads: str, monkeypatch: pytest.MonkeyPatch
):
    """T-043: yt-dlp blocking dijalankan lewat asyncio.to_thread (AGENTS.md §4.4)."""
    mock_ydl.info = dict(FULL_INFO)
    _make_output(tmp_downloads)
    main_ident = threading.get_ident()

    original = mock_ydl.extract_info
    seen: list[tuple[int, bool]] = []

    def spy(self, url, download=True, **kwargs):
        seen.append((threading.get_ident(), download))
        return original(self, url, download=download, **kwargs)

    monkeypatch.setattr(mock_ydl, "extract_info", spy)
    await download(FAKE_URL, settings)

    assert [flag for _, flag in seen] == [False, True]
    assert all(ident != main_ident for ident, _ in seen)


async def test_download_passes_built_opts(mock_ydl: type, settings: Settings, tmp_downloads: str):
    mock_ydl.info = dict(FULL_INFO)
    _make_output(tmp_downloads)
    await download(FAKE_URL, settings)

    expected = build_ydl_opts(settings.download_dir, MAX_50MB)
    for inst in mock_ydl.instances:
        assert inst.opts == expected


# ---------------- pre-check ukuran (T-044, FR-009) ----------------


@pytest.mark.parametrize("size_key", ["filesize", "filesize_approx"])
async def test_pre_check_rejects_51mb(mock_ydl: type, settings: Settings, size_key: str):
    mock_ydl.info = {"id": "BIG", "title": "big", size_key: 51 * 1024 * 1024}

    with pytest.raises(FileTooLargeError):
        await download(FAKE_URL, settings)

    # ditolak SEBELUM ada panggilan download=True
    flags = [call["download"] for inst in mock_ydl.instances for call in inst.calls]
    assert flags == [False]


async def test_pre_check_accepts_size_at_limit(
    mock_ydl: type, settings: Settings, tmp_downloads: str
):
    mock_ydl.info = {**FULL_INFO, "filesize": MAX_50MB}
    _make_output(tmp_downloads)
    result = await download(FAKE_URL, settings)
    assert isinstance(result, DownloadResult)


async def test_pre_check_skipped_when_size_unknown(
    mock_ydl: type, settings: Settings, tmp_downloads: str
):
    """Tanpa filesize/filesize_approx → lanjut download, bukan menolak."""
    mock_ydl.info = {k: v for k, v in FULL_INFO.items() if k != "filesize"}
    _make_output(tmp_downloads)
    result = await download(FAKE_URL, settings)
    assert result.metadata["filesize"] is None


# ---------------- mapping exception (T-045) ----------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Login required, this video is private", PrivateVideoError),
        ("Video unavailable. Add age confirmation", PrivateVideoError),
        ("This video is private", PrivateVideoError),
        ("Requested format is not available, 404", VideoNotFoundError),
        ("Page not found", VideoNotFoundError),
        ("Video does not exist or has been removed: 404", VideoNotFoundError),
        ("Some network hiccup", DownloadFailedError),
        ("ERROR: unable to download video data", DownloadFailedError),
    ],
)
async def test_ytdlp_error_mapping(mock_ydl: type, settings: Settings, message, expected):
    mock_ydl.extract_error = DownloadError(message)
    with pytest.raises(expected):
        await download(FAKE_URL, settings)


async def test_extractor_error_is_caught_too(mock_ydl: type, settings: Settings):
    """T-045: ExtractorError BUKAN subclass DownloadError, jadi catch base YoutubeDLError."""
    assert not issubclass(ExtractorError, DownloadError)
    assert issubclass(DownloadError, YoutubeDLError)
    assert issubclass(ExtractorError, YoutubeDLError)

    mock_ydl.extract_error = ExtractorError("Unsupported URL")
    with pytest.raises(DownloadFailedError):
        await download(FAKE_URL, settings)


async def test_mapped_error_keeps_original_as_cause(mock_ydl: type, settings: Settings):
    original = DownloadError("Page not found")
    mock_ydl.extract_error = original
    with pytest.raises(VideoNotFoundError) as exc_info:
        await download(FAKE_URL, settings)
    assert exc_info.value.__cause__ is original
    assert str(exc_info.value) == "Page not found"


async def test_file_too_large_not_masked_as_download_failed(mock_ydl: type, settings: Settings):
    """FileTooLargeError domain lolos tanpa diklasifikasi ulang."""
    mock_ydl.extract_error = FileTooLargeError("60 MB > 50 MB")
    with pytest.raises(FileTooLargeError):
        await download(FAKE_URL, settings)


async def test_missing_output_file_raises_download_failed(
    mock_ydl: type, settings: Settings, tmp_downloads: str
):
    mock_ydl.info = dict(FULL_INFO)
    # sengaja TIDAK membuat file output
    with pytest.raises(DownloadFailedError):
        await download(FAKE_URL, settings)


# ---------------- hard timeout (T-046) ----------------


def test_timeout_constant_is_60_seconds():
    assert DOWNLOAD_TIMEOUT_SECONDS == 60


async def test_hard_cap_raises_timeout_error(mock_ydl: type, settings: Settings, monkeypatch):
    """`asyncio.wait_for(..., timeout=60)` menembus yt-dlp yang menggantung.

    Timeout dipendekkan lewat monkeypatch konstanta modul (bukan替换 wait_for)
    supaya jalur `asyncio.wait_for` asli tetap teruji.
    """
    hang = threading.Event()
    mock_ydl.info = dict(FULL_INFO)

    original = mock_ydl.extract_info

    def blocking(self, url, download=True, **kwargs):
        hang.wait(timeout=5)
        return original(self, url, download=download, **kwargs)

    monkeypatch.setattr(mock_ydl, "extract_info", blocking)
    monkeypatch.setattr(downloader_mod, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(asyncio.TimeoutError):
        await download(FAKE_URL, settings)
    hang.set()


async def test_timeout_error_is_not_reclassified(mock_ydl: type, settings: Settings, monkeypatch):
    """TimeoutError harus lolos sebagai TimeoutError (WP-10 petakan ke 'Timeout')."""
    hang = threading.Event()
    mock_ydl.info = dict(FULL_INFO)
    original = mock_ydl.extract_info

    def blocking(self, url, download=True, **kwargs):
        hang.wait(timeout=5)
        return original(self, url, download=download, **kwargs)

    monkeypatch.setattr(mock_ydl, "extract_info", blocking)
    monkeypatch.setattr(downloader_mod, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(asyncio.TimeoutError) as exc_info:
        await download(FAKE_URL, settings)

    assert not isinstance(exc_info.value, DownloadFailedError)
    hang.set()
