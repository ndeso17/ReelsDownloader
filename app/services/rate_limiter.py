"""Rate limiter per-user (FR-011, WP-05).

Aturan yang mengikat modul ini (AGENTS.md):
- §4.2: semua import top-level. §4.4: fungsi publik `async def`.
- §5: tanpa secret; tidak ada I/O — murni state in-memory.

Jam dibaca lewat ``self.time_source`` (default ``time.time``) yang BISA
di-patch per-instance — test monkeypatch `rl.time_source = lambda: t`
(`freezegun` DILARANG: tidak ada di requirements, WP dilarang menambah deps).

Satu instance dibangun di bootstrap `app/main.py` dan dibagikan lewat
``application.bot_data["rate_limiter"]`` (T-055); handler WP-06 yang memanggil
``acquire``.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable

from app.config import Settings
from app.services.errors import RateLimitedError


class UserRateLimiter:
    """Tolak request chat_id yang sama dalam ``rate_limit_seconds`` (FR-011).

    State per-chat dilindungi `asyncio.Lock` per-chat (defaultdict) sehingga
    dua chat berbeda tidak pernah saling menunggu (NFR: Performance).
    """

    def __init__(
        self,
        settings: Settings | int,
        time_source: Callable[[], float] = time.time,
    ) -> None:
        # T-055 memanggil `UserRateLimiter(settings)`; int diterima untuk test.
        self.rate_limit_seconds: int = (
            settings.rate_limit_seconds if isinstance(settings, Settings) else int(settings)
        )
        self.lock_map: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_map: dict[int, float] = {}
        self.time_source: Callable[[], float] = time_source

    async def acquire(self, chat_id: int) -> None:
        """Catat request chat_id. Raise ``RateLimitedError`` bila masih dalam interval."""
        async with self.lock_map[chat_id]:
            now = float(self.time_source())
            last = self.last_map.get(chat_id)
            if last is not None and (now - last) < self.rate_limit_seconds:
                raise RateLimitedError(retry_after=self.rate_limit_seconds - (now - last))
            self.last_map[chat_id] = now

    async def clean_expired(self, max_age_seconds: float = 3600) -> None:
        """Buang entri (last_map + lock_map) yang idle lebih dari ``max_age_seconds``."""
        now = float(self.time_source())
        expired = [cid for cid, ts in self.last_map.items() if (now - ts) > max_age_seconds]
        for cid in expired:
            self.last_map.pop(cid, None)
            self.lock_map.pop(cid, None)
