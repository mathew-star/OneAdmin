"""Keyset pagination on real PostgreSQL: correctness (exhaustive walks), plan shape, query count.

The oracle for correctness is a plain ``ORDER BY`` with no pagination: walking every page
forwards or backwards must reproduce it exactly, with no duplicates and no gaps.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from oneadmin.core._typing import AnySelect
from oneadmin.core.errors import InvalidCursor
from oneadmin.core.meta import introspect
from oneadmin.core.query.cursor import CursorCodec
from oneadmin.core.query.filters import parse_filters, to_sql
from oneadmin.core.query.paginate import fetch_page, plan_page
from oneadmin.core.query.sorting import SortSpec, parse_sort
from tests.conftest import QueryCounter
from tests.integration.conftest import N_ROWS, TENANTS
from tests.models import Item, Pair

pytestmark = pytest.mark.pg

CODEC = CursorCodec("integration-test-secret-0123456789")
ITEM = introspect(Item)
PAIR = introspect(Pair)


def base(tenant: int | None = 7) -> AnySelect:
    stmt = select(Item.id, Item.grp, Item.seen_at, Item.name, Item.amount)
    return stmt.where(Item.tenant == tenant) if tenant is not None else stmt


async def oracle(session: AsyncSession, stmt: AnySelect, sort: SortSpec) -> list[Any]:
    rows = await session.execute(stmt.order_by(*sort.order_by()))
    return [tuple(r) for r in rows]


async def walk_forward(
    session: AsyncSession, stmt: AnySelect, sort: SortSpec, limit: int
) -> list[Any]:
    out: list[Any] = []
    cursor: str | None = None
    for _ in range(10_000):
        page = await fetch_page(session, stmt, sort, CODEC, limit=limit, cursor=cursor)
        out.extend(tuple(r.values()) for r in page.rows)
        if page.next_cursor is None:
            return out
        cursor = page.next_cursor
    raise AssertionError("walk did not terminate")


async def walk_backward(
    session: AsyncSession, stmt: AnySelect, sort: SortSpec, limit: int
) -> list[Any]:
    pages: list[list[Any]] = []
    page = await fetch_page(session, stmt, sort, CODEC, limit=limit, last=True)
    for _ in range(10_000):
        pages.append([tuple(r.values()) for r in page.rows])
        if page.prev_cursor is None:
            return [row for p in reversed(pages) for row in p]
        page = await fetch_page(session, stmt, sort, CODEC, limit=limit, cursor=page.prev_cursor)
    raise AssertionError("walk did not terminate")


SORTS = [
    "id",
    "-id",
    "grp",  # heavy duplicates
    "-grp",
    "-grp,id",  # mixed direction
    "grp,-amount",  # mixed, 3 keys
    "seen_at",  # nullable, NULLS LAST
    "-seen_at",  # nullable, NULLS FIRST
    "name",  # text collation
    "grp,seen_at",  # nullable non-leading -> offset mode
]


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("spec", SORTS)
async def test_walk_matches_order_by(pg_session: AsyncSession, spec: str) -> None:
    sort = parse_sort(ITEM, spec, allowed=ITEM.fields.keys())
    stmt = base()
    expected = await oracle(pg_session, stmt, sort)
    assert len(expected) == N_ROWS // TENANTS
    forward = await walk_forward(pg_session, stmt, sort, limit=97)
    assert forward == expected
    if "seen_at" not in spec.split(",")[1:]:  # backward/last not offered in offset mode
        backward = await walk_backward(pg_session, stmt, sort, limit=97)
        assert backward == expected


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("spec", ["v", "-v,a", "b"])
async def test_walk_composite_pk(pg_session: AsyncSession, spec: str) -> None:
    sort = parse_sort(PAIR, spec, allowed=PAIR.fields.keys())
    stmt = select(Pair.a, Pair.b, Pair.v)
    expected = await oracle(pg_session, stmt, sort)
    assert await walk_forward(pg_session, stmt, sort, limit=10) == expected
    assert await walk_backward(pg_session, stmt, sort, limit=10) == expected


@pytest.mark.usefixtures("seeded")
async def test_walk_with_filters(pg_session: AsyncSession) -> None:
    clauses = parse_filters(
        ITEM,
        [("f.color__in", "red,blue"), ("f.seen_at__isnull", "false"), ("f.name__icontains", "9")],
        allowed=ITEM.fields.keys(),
    )
    stmt = base().where(*(to_sql(c) for c in clauses))
    sort = parse_sort(ITEM, "-seen_at", allowed=ITEM.fields.keys())
    expected = await oracle(pg_session, stmt, sort)
    assert 0 < len(expected) < 2000
    assert await walk_forward(pg_session, stmt, sort, limit=13) == expected


@pytest.mark.usefixtures("seeded")
async def test_prev_from_page_three_equals_page_two(pg_session: AsyncSession) -> None:
    sort = parse_sort(ITEM, "-seen_at", allowed=ITEM.fields.keys())
    p1 = await fetch_page(pg_session, base(), sort, CODEC, limit=50)
    p2 = await fetch_page(pg_session, base(), sort, CODEC, limit=50, cursor=p1.next_cursor)
    p3 = await fetch_page(pg_session, base(), sort, CODEC, limit=50, cursor=p2.next_cursor)
    back = await fetch_page(pg_session, base(), sort, CODEC, limit=50, cursor=p3.prev_cursor)
    assert back.rows == p2.rows
    assert p1.prev_cursor is None


@pytest.mark.usefixtures("seeded")
async def test_empty_and_single_page(pg_session: AsyncSession) -> None:
    sort = parse_sort(ITEM, "grp", allowed=ITEM.fields.keys())
    empty = await fetch_page(pg_session, base(tenant=-1), sort, CODEC, limit=10)
    assert (empty.rows, empty.next_cursor, empty.prev_cursor) == ([], None, None)
    one = await fetch_page(pg_session, base().where(Item.id < 300), sort, CODEC, limit=10)
    assert len(one.rows) == 3
    assert one.next_cursor is None
    last = await fetch_page(pg_session, base(tenant=-1), sort, CODEC, limit=10, last=True)
    assert last.rows == []


@pytest.mark.usefixtures("seeded")
async def test_page_size_bounds(pg_session: AsyncSession) -> None:
    keyset = parse_sort(ITEM, "grp", allowed=ITEM.fields.keys())
    page = await fetch_page(pg_session, base(), keyset, CODEC, limit=5)
    assert page.next_cursor is not None
    for bad in (0, 501):
        with pytest.raises(InvalidCursor, match="page size"):
            await fetch_page(pg_session, base(), keyset, CODEC, limit=bad, cursor=page.next_cursor)


# --------------------------------------------------------------------------- plan shape


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out = [plan]
    for child in plan.get("Plans", []):
        out.extend(_nodes(child))
    return out


async def explain(session: AsyncSession, stmt: AnySelect) -> list[dict[str, Any]]:
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    raw = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {compiled}"))).scalar_one()
    return _nodes(raw[0]["Plan"])


async def deep_cursor(session: AsyncSession, sort: SortSpec, stmt: AnySelect) -> str:
    """A cursor pointing at the middle of the ordered result."""
    rows = (
        await session.execute(
            stmt.add_columns(*(k.field.expr for k in sort.keys))
            .order_by(*sort.order_by())
            .offset(N_ROWS // 2 if stmt.whereclause is None else 1000)
            .limit(1)
        )
    ).one()
    from oneadmin.core.query.cursor import Cursor  # noqa: PLC0415

    values = tuple(rows[-len(sort.keys) :])
    return CODEC.encode(sort, Cursor("after", values))


PLAN_CASES = [
    # (sort, tenant-scoped?, index expected in an Index Cond)
    ("grp", False, "ix_qe_item_grp_id"),
    ("-grp", False, "ix_qe_item_grp_id"),
    ("-grp,id", False, "ix_qe_item_grp_id"),
    ("seen_at", False, "ix_qe_item_seen_id"),
    ("-seen_at", False, "ix_qe_item_seen_id"),
    ("grp", True, "ix_qe_item_tenant_grp_id"),
]


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize(("spec", "scoped", "index"), PLAN_CASES)
async def test_deep_keyset_page_uses_index_cond(
    pg_session: AsyncSession, spec: str, scoped: bool, index: str
) -> None:
    sort = parse_sort(ITEM, spec, allowed=ITEM.fields.keys())
    stmt = base(tenant=7 if scoped else None)
    for direction in ("after", "before"):
        cursor = await deep_cursor(pg_session, sort, stmt)
        if direction == "before":
            page = await fetch_page(pg_session, stmt, sort, CODEC, limit=50, cursor=cursor)
            assert page.prev_cursor is not None
            cursor = page.prev_cursor
        plan = plan_page(stmt, sort, CODEC, dialect="postgresql", limit=50, cursor=cursor)
        nodes = await explain(pg_session, plan.query)
        kinds = {n["Node Type"] for n in nodes}
        assert "Seq Scan" not in kinds, (spec, direction, nodes)
        if "Sort" in kinds:  # a full Sort is only OK above the UNION ALL of LIMITed segments
            assert _is_outer_sort(nodes), (spec, direction, kinds)
        lead = sort.keys[0].field.name
        conds = [
            n for n in nodes if n.get("Index Name") == index and lead in n.get("Index Cond", "")
        ]
        assert conds, f"{spec}/{direction}: no Index Cond on {lead} via {index}: {nodes}"


def _is_outer_sort(nodes: list[dict[str, Any]]) -> bool:
    """A Sort is acceptable only above the UNION ALL of LIMITed segments (≤ 2*(limit+1) rows)."""
    return any(n["Node Type"] == "Append" for n in nodes)


@pytest.mark.usefixtures("seeded")
async def test_deep_page_reads_few_buffers(pg_session: AsyncSession) -> None:
    """Guard against the draft's OR-expansion regression: a deep page must not scan the index."""
    sort = parse_sort(ITEM, "grp", allowed=ITEM.fields.keys())
    cursor = await deep_cursor(pg_session, sort, base(tenant=None))
    plan = plan_page(base(tenant=None), sort, CODEC, dialect="postgresql", limit=50, cursor=cursor)
    compiled = plan.query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    raw = (
        await pg_session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}"))
    ).scalar_one()
    root = raw[0]["Plan"]
    buffers = root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0)
    assert buffers < 500, f"deep keyset page touched {buffers} buffers"


# --------------------------------------------------------------------------- query count


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("spec", ["grp", "seen_at", "-seen_at", "grp,seen_at"])
async def test_one_statement_per_page(
    pg_session: AsyncSession, count_queries: QueryCounter, spec: str
) -> None:
    sort = parse_sort(ITEM, spec, allowed=ITEM.fields.keys())
    page = await fetch_page(pg_session, base(), sort, CODEC, limit=50)
    count_queries.reset()
    await fetch_page(pg_session, base(), sort, CODEC, limit=50, cursor=page.next_cursor)
    assert count_queries.count == 1, count_queries.statements
