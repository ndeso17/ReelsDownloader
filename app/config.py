"""Konfigurasi aplikasi: 6 env var persis PRD §5 via pydantic-settings.

Token hanya lewat env (`TELEGRAM_BOT_TOKEN`) dan disimpan sebagai `SecretStr`
sehingga tidak tercetak di repr/dump (AGENTS.md §5). Tidak ada env var lain
yang dibaca: `extra="forbid"`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "ValidationError", "get_settings"]

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class Settings(BaseSettings):
    """Field persis nama env var PRD §5 dengan default PRD."""

    telegram_bot_token: SecretStr
    download_dir: str = "downloads"
    max_concurrent_downloads: int = 2
    max_file_size_mb: int = 50
    rate_limit_seconds: int = 10
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    @field_validator("log_level")
    @classmethod
    def _log_level_allowed(cls, value: str) -> str:
        if value not in _LOG_LEVELS:
            raise ValueError(f"log_level harus salah satu dari {_LOG_LEVELS}")
        return value

    @model_validator(mode="after")
    def _ranges(self) -> "Settings":
        if self.max_concurrent_downloads < 1:
            raise ValueError("max_concurrent_downloads harus >= 1")
        if self.max_file_size_mb < 1:
            raise ValueError("max_file_size_mb harus >= 1")
        if self.rate_limit_seconds < 0:
            raise ValueError("rate_limit_seconds harus >= 0")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Satu instance Settings per proses (cache), dipanggil sekali di entrypoint."""
    return Settings()
