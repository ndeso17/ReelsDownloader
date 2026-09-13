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
_BOT_MODES = ("public", "private")


class Settings(BaseSettings):
    """Field persis nama env var PRD §5 dengan default PRD."""

    telegram_bot_token: SecretStr
    download_dir: str = "downloads"
    max_concurrent_downloads: int = 2
    max_file_size_mb: int = 50
    rate_limit_seconds: int = 10
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    bot_mode: Literal["public", "private"] = "public"
    owner_user_id: int | None = None
    authorized_user_ids: str = ""
    users_file: str = "users.json"
    admin_notify_chat_id: int | None = None
    stats_file: str = "stats.json"
    queue_max_size: int = 20
    max_queue_wait_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    @field_validator("log_level")
    @classmethod
    def _log_level_allowed(cls, value: str) -> str:
        if value not in _LOG_LEVELS:
            raise ValueError(f"log_level harus salah satu dari {_LOG_LEVELS}")
        return value

    @field_validator("owner_user_id", "admin_notify_chat_id", mode="before")
    @classmethod
    def _coerce_empty_str_to_none(cls, value):
        if value == "" or value is None:
            return None
        return value

    def authorized_ids_set(self) -> frozenset[int]:
        raw = (getattr(self, "authorized_user_ids", "") or "").strip()
        if not raw:
            return frozenset()
        ids: list[int] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ids.append(int(token))
            except ValueError as exc:
                raise ValueError(f"AUTHORIZED_USER_IDS berisi token non-angka: {token!r}") from exc
        return frozenset(ids)

    @property
    def admin_chat_id(self) -> int | None:
        notify = getattr(self, "admin_notify_chat_id", None)
        if notify is not None:
            return notify
        return getattr(self, "owner_user_id", None)

    @model_validator(mode="after")
    def _ranges(self) -> "Settings":
        if self.max_concurrent_downloads < 1:
            raise ValueError("max_concurrent_downloads harus >= 1")
        if self.max_file_size_mb < 1:
            raise ValueError("max_file_size_mb harus >= 1")
        if self.rate_limit_seconds < 0:
            raise ValueError("rate_limit_seconds harus >= 0")
        if self.bot_mode == "private" and self.owner_user_id is None:
            raise ValueError("owner_user_id wajib diisi saat bot_mode=private")
        if self.queue_max_size < 1:
            raise ValueError("queue_max_size harus >= 1")
        if self.max_queue_wait_seconds < 1:
            raise ValueError("max_queue_wait_seconds harus >= 1")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Satu instance Settings per proses (cache), dipanggil sekali di entrypoint."""
    return Settings()
