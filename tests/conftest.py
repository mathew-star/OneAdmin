"""Shared fixtures.

PostgreSQL resolution order:
1. ``ONEADMIN_TEST_PG_URL`` (e.g. a CI service container or a local server), else
2. a session-scoped testcontainers ``postgres:17-alpine``.

Each test that uses ``pg_session`` runs inside an outer transaction that is rolled back,
so tests are isolated and fast. Code under test may call ``session.commit()`` freely:
the session is bound with ``join_transaction_mode="create_savepoint"``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

PG_IMAGE = os.environ.get("ONEADMIN_TEST_PG_IMAGE", "postgres:17-alpine")


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    url = os.environ.get("ONEADMIN_TEST_PG_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers not installed and ONEADMIN_TEST_PG_URL not set")
    try:
        container = PostgresContainer(PG_IMAGE, driver="asyncpg")
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        if os.environ.get("ONEADMIN_REQUIRE_PG") == "1":
            raise  # CI must never silently skip the Postgres suite
        pytest.skip(f"PostgreSQL unavailable (Docker not running?): {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
async def pg_engine(pg_url: str) -> AsyncIterator[AsyncEngine]:
    # lock_timeout: a fixture/test lock-ordering bug fails fast instead of hanging the run.
    engine = create_async_engine(
        pg_url, pool_size=5, connect_args={"server_settings": {"lock_timeout": "10s"}}
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@dataclass
class QueryCounter:
    """Counts SQL statements executed on an engine (N+1 regression guard)."""

    statements: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.statements)

    def reset(self) -> None:
        self.statements.clear()


@pytest.fixture
def count_queries(pg_engine: AsyncEngine) -> Iterator[QueryCounter]:
    counter = QueryCounter()

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        # Savepoint bookkeeping is test-harness noise, not application queries.
        if (
            not statement.lstrip()
            .upper()
            .startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO"))
        ):
            counter.statements.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", _on_execute)
