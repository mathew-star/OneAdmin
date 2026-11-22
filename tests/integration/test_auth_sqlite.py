"""The built-in login on SQLite, which the README supports for development.

Regression: SQLite returns ``DateTime(timezone=True)`` values *naive*, so session checks
raised ``TypeError: can't compare offset-naive and offset-aware datetimes`` on the first
authenticated request (found by the M4 browser tests). ``UTCDateTime`` fixes it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oneadmin.auth import migrate
from oneadmin.auth import tables as t
from oneadmin.auth.service import AuthService, AuthSettings, InvalidCredentials, RateLimited

EMAIL = "dev@example.com"
PASSWORD = "a long enough password"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    await migrate.upgrade(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def auth(engine: AsyncEngine, clock: Clock) -> AuthService:
    service = AuthService(
        async_sessionmaker(engine, expire_on_commit=False),
        "s" * 32,
        AuthSettings(max_failures_per_email=2),
        clock=clock,
    )
    await service.create_user(EMAIL, PASSWORD, is_superuser=True)
    return service


async def test_session_lifecycle(auth: AuthService, clock: Clock) -> None:
    token = (await auth.login(EMAIL, PASSWORD)).token
    identity = await auth.resolve(token)
    assert identity is not None
    assert identity.email == EMAIL

    clock.now += timedelta(hours=1, minutes=59)
    assert await auth.resolve(token) is not None, "activity within the idle window"
    clock.now += timedelta(hours=2, seconds=1)
    assert await auth.resolve(token) is None, "idle timeout"

    token = (await auth.login(EMAIL, PASSWORD)).token
    await auth.logout(token)
    assert await auth.resolve(token) is None


async def test_rate_limit_window(auth: AuthService, clock: Clock) -> None:
    for _ in range(2):
        with pytest.raises(InvalidCredentials):
            await auth.login(EMAIL, "wrong password here")
    with pytest.raises(RateLimited):
        await auth.login(EMAIL, PASSWORD)
    clock.now += timedelta(minutes=15, seconds=1)
    assert (await auth.login(EMAIL, PASSWORD)).token


async def test_timestamps_come_back_aware_utc(auth: AuthService, engine: AsyncEngine) -> None:
    await auth.login(EMAIL, PASSWORD)
    async with engine.connect() as conn:
        created = (await conn.execute(select(t.session.c.created_at))).scalar_one()
    assert created == datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert created.utcoffset() == timedelta(0)
