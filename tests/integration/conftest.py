"""Shared, session-scoped seeded data for query-engine integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.models import TBase

N_ROWS = 200_000
TENANTS = 100  # => 2,000 rows per tenant: the walk tests run tenant-scoped


@pytest.fixture(scope="session")
async def seeded(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    async with pg_engine.begin() as conn:
        await conn.run_sync(TBase.metadata.drop_all)
        await conn.run_sync(TBase.metadata.create_all)
        await conn.execute(
            text(
                f"""
                INSERT INTO qe_item (id, tenant, grp, seen_at, name, note, amount, color, slug)
                SELECT g, g % {TENANTS}, g % 5,
                  CASE WHEN g % 3 = 0 THEN NULL
                       ELSE timestamptz '2026-01-01Z' + (g % 1000) * interval '1 minute' END,
                  'name ' || (g % 997),
                  CASE WHEN g % 2 = 0 THEN NULL ELSE 'note ' || g END,
                  (g % 300) / 3.0,
                  (ARRAY['RED','GREEN','BLUE'])[1 + g % 3]::qe_color,
                  CASE WHEN g % 7 = 0 THEN NULL ELSE 's' || (g % 50) END
                FROM generate_series(1, {N_ROWS}) g
                """
            )
        )
        await conn.execute(
            text(
                "INSERT INTO qe_pair (a, b, v) SELECT g % 13, 'k' || (g % 31), g % 4 "
                "FROM generate_series(1, 403) g ON CONFLICT DO NOTHING"
            )
        )
    async with pg_engine.connect() as conn:
        auto = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await auto.execute(text("ANALYZE qe_item"))
        await auto.execute(text("ANALYZE qe_pair"))
    yield
    async with pg_engine.begin() as conn:
        await conn.run_sync(TBase.metadata.drop_all)
