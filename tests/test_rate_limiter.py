"""Tests rate limiter per-user (T-054, WP-05, FR-011).

Mock clock lewat patch atribut instance `rl.time_source = lambda: t` —
`freezegun` DILARANG (tidak ada di requirements; WP dilarang menambah deps).
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.errors import RateLimitedError
from app.services.rate_limiter import UserRateLimiter

INTERVAL = 10


@pytest.fixture
def rl() -> UserRateLimiter:
    return UserRateLimiter(INTERVAL)


async def test_second_request_under_interval_raises(rl: UserRateLimiter) -> None:
    t = 0.0
    rl.time_source = lambda: t
    await rl.acquire(1)
    t = 5.0  # < 10s sejak request pertama
    with pytest.raises(RateLimitedError) as exc_info:
        await rl.acquire(1)
    assert exc_info.value.retry_after == pytest.approx(5.0)
    assert exc_info.value.retry_after > 0


async def test_second_request_over_interval_passes(rl: UserRateLimiter) -> None:
    t = 0.0
    rl.time_source = lambda: t
    await rl.acquire(1)
    t = 15.0  # > 10s — harus lolos
    await rl.acquire(1)
    assert rl.last_map[1] == 15.0


async def test_concurrent_different_chat_ids_do_not_block(rl: UserRateLimiter) -> None:
    rl.time_source = lambda: 0.0
    await asyncio.gather(rl.acquire(1), rl.acquire(2))
    assert rl.last_map == {1: 0.0, 2: 0.0}
    # chat 3 dan 4 pun tetap lolos meskipun chat 1/2 baru saja request
    await asyncio.gather(rl.acquire(3), rl.acquire(4))
    assert set(rl.last_map) == {1, 2, 3, 4}


async def test_concurrent_same_chat_id_second_denied(rl: UserRateLimiter) -> None:
    """Race guard: dua acquire() paralel chat sama — tepat satu lolos (lock per-user)."""
    rl.time_source = lambda: 0.0
    results = await asyncio.gather(rl.acquire(1), rl.acquire(1), return_exceptions=True)
    ok = [r for r in results if r is None]
    denied = [r for r in results if isinstance(r, RateLimitedError)]
    assert len(ok) == 1
    assert len(denied) == 1


async def test_clean_expired_removes_old_entries(rl: UserRateLimiter) -> None:
    current = 1000.0
    rl.time_source = lambda: current
    await rl.acquire(1)  # last_map[1] = 1000.0
    current = 1200.0
    await rl.acquire(2)  # last_map[2] = 1200.0
    current = 5000.0  # entri chat 1 berumur 4000s > max_age
    await rl.clean_expired(max_age_seconds=3600)
    assert 1 not in rl.last_map
    assert 2 not in rl.last_map  # 3800s idle pun ikut terbuang
    assert not rl.lock_map


async def test_clean_expired_keeps_fresh_entries(rl: UserRateLimiter) -> None:
    current = 1000.0
    rl.time_source = lambda: current
    await rl.acquire(7)
    current = 2000.0  # idle 1000s < 3600s
    await rl.clean_expired()
    assert 7 in rl.last_map
    assert 7 in rl.lock_map
