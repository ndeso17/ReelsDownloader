"""Fixture test reusable untuk WP-04..WP-12 (T-048).

MockYDL mengisolasi yt-dlp: tidak ada test menyentuh Instagram/Facebook nyata
(AGENTS.md §4.6). Update satu tempat bila signature yt-dlp berubah.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class MockYDL:
    """Drop-in stub `yt_dlp.YoutubeDL` untuk test tanpa network."""

    #: class-level agar test bisa mengatur ulang lewat `MockYDL.reset()`
    info: dict | None = None
    extract_error: Exception | None = None
    download_error: Exception | None = None
    prepare_filename_value: str | None = None

    #: rekam semua instance yang dibuat (assert opts / jumlah panggilan)
    instances: list[MockYDL] = []

    def __init__(self, opts=None):
        self.opts = dict(opts or {})
        self.calls: list[dict] = []
        MockYDL.instances.append(self)

    # --- context manager seperti YoutubeDL asli ---
    def __enter__(self) -> MockYDL:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def extract_info(self, url, download=True, **kwargs):
        self.calls.append({"url": url, "download": download, "kwargs": kwargs})
        if download:
            if MockYDL.download_error is not None:
                raise MockYDL.download_error
        elif MockYDL.extract_error is not None:
            raise MockYDL.extract_error
        info = MockYDL.info
        if info is None:
            return None
        return dict(info)

    def prepare_filename(self, info, outtmpl=None):
        if MockYDL.prepare_filename_value is not None:
            return MockYDL.prepare_filename_value
        outtmpl_value = self.opts.get("outtmpl") or outtmpl
        if isinstance(outtmpl_value, dict):
            outtmpl_value = outtmpl_value["default"]
        download_dir = Path(outtmpl_value).parent if outtmpl_value else Path(".")
        return str(download_dir / f"{info.get('id', 'unknown')}.{info.get('ext', 'mp4')}")

    @classmethod
    def reset(cls) -> None:
        cls.info = None
        cls.extract_error = None
        cls.download_error = None
        cls.prepare_filename_value = None
        cls.instances = []


@pytest.fixture
def tmp_downloads(tmp_path: Path) -> str:
    """Dir sementara untuk outtmpl, path terkendali kode, bukan user."""
    target = tmp_path / "downloads"
    target.mkdir()
    return str(target)


@pytest.fixture
def mock_ydl(monkeypatch, tmp_downloads: str):
    """Patch `yt_dlp.YoutubeDL` -> MockYDL; kembalikan kelas MockYDL."""
    MockYDL.reset()
    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)
    return MockYDL
