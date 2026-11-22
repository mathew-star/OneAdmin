"""Smoke test: the example domain creates cleanly on PostgreSQL and the harness isolates tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from examples.shop.models import Base, Tenant
from tests.conftest import QueryCounter

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
async def shop_schema(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.usefixtures("shop_schema")
async def test_commit_inside_test_is_rolled_back_afterwards(pg_session: AsyncSession) -> None:
    pg_session.add(Tenant(id=1, name="acme"))
    await pg_session.commit()  # savepoint, not a real commit
    assert await pg_session.scalar(select(func.count()).select_from(Tenant)) == 1


@pytest.mark.usefixtures("shop_schema")
async def test_previous_test_left_no_rows(pg_session: AsyncSession) -> None:
    assert await pg_session.scalar(select(func.count()).select_from(Tenant)) == 0


@pytest.mark.usefixtures("shop_schema")
async def test_query_counter_counts_statements(
    pg_session: AsyncSession, count_queries: QueryCounter
) -> None:
    await pg_session.execute(select(Tenant.id))
    await pg_session.execute(select(Tenant.name))
    assert count_queries.count == 2
