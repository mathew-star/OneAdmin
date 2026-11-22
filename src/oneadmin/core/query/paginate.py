"""Fetch one page of a list query, in keyset or offset mode, with exactly one SQL statement.

``plan_page`` builds the statement without executing it, so tests and ``oneadmin check`` can
``EXPLAIN`` exactly what will run. ``fetch_page`` executes the plan and builds cursors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from oneadmin.core._typing import AnySelect
from oneadmin.core.errors import InvalidCursor
from oneadmin.core.query.cursor import Cursor, CursorCodec
from oneadmin.core.query.keyset import PaginationMode, keyset_segments, pagination_mode
from oneadmin.core.query.sorting import SortSpec

MAX_PAGE_SIZE = 500
_KEY = "_oa_k{}"
_PHASE = "_oa_phase"


@dataclass(frozen=True, slots=True)
class Page:
    rows: list[dict[str, Any]]
    next_cursor: str | None
    prev_cursor: str | None
    mode: PaginationMode


@dataclass(frozen=True, slots=True)
class PagePlan:
    query: AnySelect
    sort: SortSpec
    mode: PaginationMode
    limit: int
    labels: tuple[str, ...]
    backward: bool
    last: bool
    has_cursor: bool
    offset: int


def plan_page(
    stmt: AnySelect,
    sort: SortSpec,
    codec: CursorCodec,
    *,
    dialect: str,
    limit: int,
    cursor: str | None = None,
    last: bool = False,
) -> PagePlan:
    """Build the page query for ``stmt`` (scoped and filtered, without ORDER BY or LIMIT)."""
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidCursor(f"page size must be between 1 and {MAX_PAGE_SIZE}", param="limit")
    mode = pagination_mode(sort)
    decoded = codec.decode(sort, cursor) if cursor else None
    if decoded is not None and (decoded.offset is None) != (mode == "keyset"):
        raise InvalidCursor("cursor does not match this list's pagination mode", param="cursor")
    labels = tuple(_KEY.format(i) for i in range(len(sort.keys)))
    keyed = stmt.add_columns(
        *(k.field.expr.label(lbl) for k, lbl in zip(sort.keys, labels, strict=True))
    )

    if mode == "offset":
        if last:
            raise InvalidCursor("'last page' is not available for this sort", param="last")
        start = decoded.offset if decoded is not None and decoded.offset is not None else 0
        query = keyed.order_by(*sort.order_by()).offset(start).limit(limit + 1)
        return PagePlan(query, sort, mode, limit, labels, False, False, decoded is not None, start)

    backward = last or (decoded is not None and decoded.direction == "before")
    exec_sort = sort.reversed() if backward else sort
    segments = (
        keyset_segments(exec_sort, decoded.values, dialect=dialect)
        if decoded is not None and decoded.values is not None
        else []
    )
    if len(segments) <= 1:
        query = keyed.where(*segments).order_by(*exec_sort.order_by()).limit(limit + 1)
    else:
        # One LIMITed, index-friendly branch per segment; the outer query orders by segment.
        branches = [
            select(
                keyed.where(seg)
                .order_by(*exec_sort.order_by())
                .limit(limit + 1)
                .add_columns(literal(i, Integer).label(_PHASE))
                .subquery()
            )
            for i, seg in enumerate(segments)
        ]
        page = union_all(*branches).subquery("oa_page")
        query = (
            select(*(c for c in page.c if c.key != _PHASE))
            .order_by(
                page.c[_PHASE],
                *(k.order_by(page.c[lbl]) for k, lbl in zip(exec_sort.keys, labels, strict=True)),
            )
            .limit(limit + 1)
        )
    return PagePlan(query, sort, mode, limit, labels, backward, last, decoded is not None, 0)


async def fetch_page(
    session: AsyncSession,
    stmt: AnySelect,
    sort: SortSpec,
    codec: CursorCodec,
    *,
    limit: int,
    cursor: str | None = None,
    last: bool = False,
) -> Page:
    """Run one page. ``last=True`` without a cursor returns the final page."""
    plan = plan_page(
        stmt,
        sort,
        codec,
        dialect=session.get_bind().dialect.name,
        limit=limit,
        cursor=cursor,
        last=last,
    )
    rows = [dict(r) for r in (await session.execute(plan.query)).mappings()]
    return build_page(plan, rows, codec)


def build_page(plan: PagePlan, rows: list[dict[str, Any]], codec: CursorCodec) -> Page:
    limit, sort, labels = plan.limit, plan.sort, plan.labels
    has_more = len(rows) > limit
    rows = rows[:limit]

    if plan.mode == "offset":
        start = plan.offset
        nxt = codec.encode(sort, Cursor("after", offset=start + limit)) if has_more else None
        prv = (
            codec.encode(sort, Cursor("after", offset=max(0, start - limit))) if start > 0 else None
        )
        return Page(_strip(rows, labels), nxt, prv, plan.mode)

    if plan.backward:
        rows.reverse()

    def edge(row: dict[str, Any], direction: str) -> str:
        values = tuple(row[lbl] for lbl in labels)
        return codec.encode(sort, Cursor("after" if direction == "after" else "before", values))

    if not plan.backward:
        nxt = edge(rows[-1], "after") if rows and has_more else None
        prv = edge(rows[0], "before") if rows and plan.has_cursor else None
    else:
        prv = edge(rows[0], "before") if rows and has_more else None
        nxt = edge(rows[-1], "after") if rows and not plan.last else None
    return Page(_strip(rows, labels), nxt, prv, plan.mode)


def _strip(rows: list[dict[str, Any]], labels: tuple[str, ...]) -> list[dict[str, Any]]:
    for row in rows:
        for lbl in labels:
            row.pop(lbl, None)
    return rows
