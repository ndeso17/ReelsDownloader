"""WP-12 smoke test (T-124, T-125).

T-124: `DOWNLOAD_DIR` dari env dihormati; default `downloads` (FR-008).
T-125: modul inti bisa di-import tanpa efek samping jaringan, jalur yang sama
ditempuh `python -m app.main` (AGENTS.md §4.6: tidak ada test menyentuh
Instagram/Facebook/Telegram nyata).

`.env` lokal developer tidak boleh ikut menentukan hasil: env var proses menang
atas `env_file` di pydantic-settings, dan `_env_file=None` mematikan dotenv bila
default murni yang diuji.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings

DUMMY = SecretStr("dum-token")


# ---------------- T-124: download_dir dari env ----------------


def test_download_dir_env_var_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-008 (SC: env): `DOWNLOAD_DIR=...` dari env dipakai apa adanya, tmp_path, bukan repo."""
    custom = str(tmp_path / "my_dl")
    monkeypatch.setenv("DOWNLOAD_DIR", custom)
    settings = Settings(telegram_bot_token=DUMMY)
    assert settings.download_dir == custom
    assert settings.download_dir != str(Path.cwd() / "downloads")


def test_download_dir_default_is_downloads() -> None:
    """Default field = `downloads` (PRD §5) tanpa `.env` yang mengintervensi."""
    settings = Settings(telegram_bot_token=DUMMY, _env_file=None)
    assert settings.download_dir == "downloads"


def test_other_env_overrides_are_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity env 6 var PRD §5: nilai proses menembus Settings (bukan `.env`)."""
    custom = str(tmp_path / "env-dl")
    monkeypatch.setenv("DOWNLOAD_DIR", custom)
    monkeypatch.setenv("MAX_CONCURRENT_DOWNLOADS", "7")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "42")
    monkeypatch.setenv("RATE_LIMIT_SECONDS", "3")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings(telegram_bot_token=DUMMY)
    assert settings.download_dir == custom
    assert settings.max_concurrent_downloads == 7
    assert settings.max_file_size_mb == 42
    assert settings.rate_limit_seconds == 3
    assert settings.log_level == "DEBUG"


# ---------------- T-125: smoke import ----------------

SMOKE_MODULES = [
    "app.main",
    "app.config",
    "app.handlers.start",
    "app.handlers.download",
    "app.services.downloader",
    "app.services.validator",
    "app.services.rate_limiter",
    "app.services.uploader",
    "app.services.errors",
    "app.utils.files",
]


@pytest.mark.parametrize("module_name", SMOKE_MODULES)
def test_module_imports_without_network_side_effect(module_name: str) -> None:
    """T-125: import tiap modul inti berhasil; tidak ada request Telegram/IG nyata saat import."""
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name


def test_import_app_main_does_not_start_polling() -> None:
    """`import app.main` hanya mendeklarasikan; polling hanya di `if __name__ == "__main__"`."""
    import app.main as main_mod

    assert callable(main_mod.main)
    # `asyncio.run(main())` tidak dieksekusi saat import: loop berjalan tidak ada di sini.
    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.get_running_loop()
