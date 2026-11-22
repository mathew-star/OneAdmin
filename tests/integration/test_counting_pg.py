from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Column as C
from sqlalchemy import Integer, MetaData, Table, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from oneadmin.core.query.counting import count_rows
from tests.integration.conftest import N_ROWS
from tests.models import Item

pytestmark = [pytest.mark.pg, pytest.mark.usefixtures("seeded")]

ALL = select(Item.id)
FILTERED = select(Item.id).where(Item.grp == 1)  # 40,000 rows


async def test_auto_uses_estimate_when_unfiltered(pg_session: AsyncSession) -> None:
    c = await count_rows(pg_session, ALL, qualified_table="qe_item")
    assert c.method == "estimate"
    assert not c.exact
    assert abs((c.value or 0) - N_ROWS) / N_ROWS < 0.05


async def test_estimate_never_used_for_filtered_statements(pg_session: AsyncSession) -> None:
    """Scoped admins must not learn the global row count through the estimate."""
    c = await count_rows(pg_session, FILTERED, strategy="estimate", qualified_table="qe_item")
    assert (c.value, c.exact, c.method) == (10_000, False, "capped")


async def test_auto_small_table_is_exact(pg_session: AsyncSession) -> None:
    c = await count_rows(pg_session, ALL, qualified_table="qe_item", estimate_threshold=10**9)
    assert c.method == "capped"
    assert not c.exact
    assert c.value == 10_000
    c = await count_rows(pg_session, select(Item.id).where(Item.tenant == 7))
    assert (c.value, c.exact) == (2_000, True)


async def test_exact(pg_session: AsyncSession) -> None:
    c = await count_rows(pg_session, FILTERED, strategy="exact")
    assert (c.value, c.exact) == (N_ROWS // 5, True)


async def test_none(pg_session: AsyncSession) -> None:
    c = await count_rows(pg_session, FILTERED, strategy="none")
    assert c.value is None


@pytest.fixture
async def never_analyzed(pg_engine: AsyncEngine) -> AsyncIterator[Table]:
    md = MetaData()
    t = Table("qe_fresh", md, C("id", Integer, primary_key=True))
    async with pg_engine.begin() as conn:
        await conn.run_sync(md.create_all)
        await conn.execute(text("INSERT INTO qe_fresh SELECT generate_series(1, 500)"))
    yield t
    async with pg_engine.begin() as conn:
        await conn.run_sync(md.drop_all)


async def test_reltuples_minus_one_falls_back(
    never_analyzed: Table,  # must precede pg_session: its DROP runs after the test txn ends
    pg_session: AsyncSession,
) -> None:
    reltuples = (
        await pg_session.execute(text("SELECT reltuples FROM pg_class WHERE relname='qe_fresh'"))
    ).scalar_one()
    assert reltuples == -1, "precondition: table has never been analyzed"
    c = await count_rows(
        pg_session, select(never_analyzed.c.id), strategy="estimate", qualified_table="qe_fresh"
    )
    assert (c.value, c.exact) == (500, True)


async def test_unknown_table_name_falls_back(pg_session: AsyncSession) -> None:
    c = await count_rows(pg_session, ALL, strategy="estimate", qualified_table="no.such_table")
    assert c.method == "capped"


async def test_timeout_returns_unknown_and_session_survives(pg_session: AsyncSession) -> None:
    slow = select(Item.id).where(func.pg_sleep(0.0001).is_(None) | (Item.grp >= 0))
    before = (await pg_session.execute(text("SHOW statement_timeout"))).scalar_one()
    c = await count_rows(pg_session, slow, strategy="exact", timeout_ms=1)
    assert (c.value, c.method) == (None, "timeout")
    # The savepoint rolled back cleanly: the session works and the timeout was not left set.
    assert (await pg_session.execute(select(func.count()).select_from(Item))).scalar_one() > 0
    after = (await pg_session.execute(text("SHOW statement_timeout"))).scalar_one()
    assert after == before


async def test_successful_count_restores_statement_timeout(pg_session: AsyncSession) -> None:
    before = (await pg_session.execute(text("SHOW statement_timeout"))).scalar_one()
    await count_rows(pg_session, FILTERED, strategy="exact", timeout_ms=5_000)
    assert (await pg_session.execute(text("SHOW statement_timeout"))).scalar_one() == before
