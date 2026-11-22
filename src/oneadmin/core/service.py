"""Read services: list, count and detail.

This is the only request-path layer that builds SQL. ``oneadmin.api`` calls it and receives
ORM-neutral, wire-safe results (ADR-0017).

A list page is exactly one statement (ADR-0006, CLAUDE.md invariant 5)::

    SELECT pk, <list columns>, <fk label per relation>, <sort keys>
    FROM model
    LEFT OUTER JOIN (<target admin's *scoped* SELECT pk, label>) AS oa_rel_<name>
        ON model.<fk> = oa_rel_<name>.pk
    WHERE <this admin's scope> AND <filters> AND <search> AND <keyset predicate>
    ORDER BY <sort keys> LIMIT n + 1

Labels go through the *target* admin's scope (``apply_scope``). A row the user may see can point at
a row they may not see; that label comes back as ``null`` rather than leaking. When a count is
requested, it runs concurrently on a second session (ADR-0004).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from oneadmin.core._typing import AnySelect
from oneadmin.core.context import AdminContext
from oneadmin.core.meta import FieldMeta
from oneadmin.core.model_admin import CompiledAdmin, ModelAdmin, RelationSpec
from oneadmin.core.query.counting import Count, Strategy, count_rows
from oneadmin.core.query.cursor import CursorCodec
from oneadmin.core.query.filters import parse_filters, to_sql
from oneadmin.core.query.keyset import PaginationMode
from oneadmin.core.query.paginate import fetch_page
from oneadmin.core.query.search import search_clause
from oneadmin.core.query.sorting import parse_sort
from oneadmin.core.versioning import RowVersioner
from oneadmin.core.wire import decode_pk, encode_pk, to_wire

A = TypeVar("A")
B = TypeVar("B")
T = TypeVar("T")

AdminLookup = Callable[[type[Any]], ModelAdmin | None]
"""Finds the primary admin registered for a model, or ``None`` if it isn't registered."""


@dataclass(frozen=True, slots=True)
class ListParams:
    """Client-supplied list parameters, still unvalidated (validation happens here)."""

    sort: str | None = None
    q: str | None = None
    filters: Sequence[tuple[str, str]] = ()
    """``(key, value)`` pairs whose keys start with ``f.``; see ``query.filters``."""
    cursor: str | None = None
    limit: int | None = None
    last: bool = False
    with_count: bool = True


@dataclass(frozen=True, slots=True)
class WireRow:
    pk: str
    """Encoded primary key, usable in detail URLs."""
    values: dict[str, Any]
    """JSON-safe values keyed by field or relation name."""
    version: str | None = None
    """Concurrency token of a detail read; send it back as ``If-Match`` (ADR-0018)."""


@dataclass(frozen=True, slots=True)
class ListResult:
    rows: list[WireRow]
    next_cursor: str | None
    prev_cursor: str | None
    mode: PaginationMode
    count: Count | None


class ReadService:
    """Read operations for every admin of one ``AdminSite``."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        codec: CursorCodec,
        lookup: AdminLookup,
        versions: RowVersioner,
    ) -> None:
        self._session_factory = session_factory
        self._codec = codec
        self._lookup = lookup
        self._versions = versions

    # ---- public operations ---------------------------------------------------------------
    async def list(self, ctx: AdminContext, admin: ModelAdmin, params: ListParams) -> ListResult:
        """One page of rows, plus (optionally) a cheap count, in parallel."""
        c = admin.compiled
        sort = parse_sort(c.meta, params.sort, allowed=c.sort_allowed, default=c.default_sort)
        # Build (and so validate) every statement before starting any I/O.
        page_stmt = await self._list_statement(ctx, admin, params)
        wants_count = params.with_count and admin.count_strategy != "none"
        count_stmt = await self._count_statement(ctx, admin, params) if wants_count else None

        def page_job() -> Any:
            return fetch_page(
                ctx.session,
                page_stmt,
                sort,
                self._codec,
                limit=params.limit or admin.list_per_page,
                cursor=params.cursor,
                last=params.last,
            )

        count: Count | None = None
        if count_stmt is None:
            page = await page_job()
        elif admin.count_concurrently:
            async with self._session_factory() as count_session:
                page, count = await _together(
                    page_job(), self._count(count_session, c, count_stmt, admin.count_strategy)
                )
        else:
            page = await page_job()
            count = await self._count(ctx.session, c, count_stmt, admin.count_strategy)

        rows = [self._shape(c, row, c.list_columns, c.list_relations) for row in page.rows]
        return ListResult(rows, page.next_cursor, page.prev_cursor, page.mode, count)

    async def count(self, ctx: AdminContext, admin: ModelAdmin, params: ListParams) -> Count:
        """Exact count of the filtered, scoped list (the on-demand "count exactly" button)."""
        stmt = await self._count_statement(ctx, admin, params)
        return await self._count(ctx.session, admin.compiled, stmt, "exact")

    async def get(self, ctx: AdminContext, admin: ModelAdmin, raw_pk: str) -> WireRow | None:
        """One row by encoded primary key, scoped.

        Returns ``None`` both for rows that don't exist and for rows outside the caller's
        scope, so the API can't be used to probe for the existence of other tenants' rows.
        """
        c = admin.compiled
        try:
            pk_values = decode_pk(c.meta, raw_pk)
        except (ValueError, KeyError):
            return None
        stmt = select(*_labelled(c.detail_fields)).select_from(c.model)
        stmt = await self._join_labels(ctx, stmt, c.detail_relations)
        stmt = await admin.apply_scope(ctx, stmt)
        stmt = stmt.where(*(pk.expr == v for pk, v in zip(c.meta.pk, pk_values, strict=True)))
        rows = (await ctx.session.execute(stmt.limit(2))).mappings().all()
        if len(rows) != 1:  # 2 would mean the scope hook joined in duplicates; refuse to guess
            return None
        row = self._shape(c, dict(rows[0]), c.detail_fields, c.detail_relations)
        return WireRow(row.pk, row.values, self._versions.of_values(c, row.values))

    # ---- statement builders --------------------------------------------------------------
    async def _list_statement(
        self, ctx: AdminContext, admin: ModelAdmin, params: ListParams
    ) -> AnySelect:
        c = admin.compiled
        hidden_fks = [r.local for r in c.list_relations if r.local not in c.list_columns]
        stmt = select(*_labelled((*c.list_columns, *hidden_fks))).select_from(c.model)
        stmt = await self._join_labels(ctx, stmt, c.list_relations)
        stmt = await admin.apply_scope(ctx, stmt)
        return _filter(c, stmt, params)

    async def _count_statement(
        self, ctx: AdminContext, admin: ModelAdmin, params: ListParams
    ) -> AnySelect:
        """PK-only, without label joins: as cheap as the scope and filters allow."""
        c = admin.compiled
        stmt = select(*(pk.expr for pk in c.meta.pk)).select_from(c.model)
        stmt = await admin.apply_scope(ctx, stmt)
        return _filter(c, stmt, params)

    async def _join_labels(
        self, ctx: AdminContext, stmt: AnySelect, relations: Iterable[RelationSpec]
    ) -> AnySelect:
        for rel in relations:
            target = self._lookup(rel.target)
            if target is None:
                continue  # unregistered target: raw FK only, never an unscoped label
            label_query = select(
                rel.remote_column.label("pk"), target.compiled.label.expr.label("label")
            ).select_from(target.compiled.model)
            labels = (await target.apply_scope(ctx, label_query)).subquery(f"oa_rel_{rel.name}")
            stmt = stmt.outerjoin(labels, rel.local.expr == labels.c.pk).add_columns(
                labels.c.label.label(_label_key(rel))
            )
        return stmt

    async def _count(
        self, session: AsyncSession, c: CompiledAdmin, stmt: AnySelect, strategy: Strategy
    ) -> Count:
        table = c.meta.mapper.local_table
        qualified = None
        if isinstance(table, Table):  # enables reltuples estimates on PostgreSQL
            qualified = session.get_bind().dialect.identifier_preparer.format_table(table)
        return await count_rows(session, stmt, strategy=strategy, qualified_table=qualified)

    # ---- result shaping ------------------------------------------------------------------
    def _shape(
        self,
        c: CompiledAdmin,
        row: dict[str, Any],
        fields: Iterable[FieldMeta],
        relations: Iterable[RelationSpec],
    ) -> WireRow:
        pk = encode_pk(c.meta, tuple(row[p.name] for p in c.meta.pk))
        values: dict[str, Any] = {f.name: to_wire(row[f.name]) for f in fields}
        for rel in relations:
            if self._lookup(rel.target) is not None:
                values[rel.name] = _relation_value(row[rel.local.name], row[_label_key(rel)])
        return WireRow(pk, values)


async def _together(first: Awaitable[A], second: Awaitable[B]) -> tuple[A, B]:
    """Run two awaitables concurrently; if one fails, cancel the other and re-raise its error.

    ``asyncio.gather`` would leave the sibling running (on a session we are about to close);
    a ``TaskGroup`` cancels it. The single failure is unwrapped from the ``ExceptionGroup`` so
    callers (and the API's error mapping) see the original exception type.
    """
    try:
        async with asyncio.TaskGroup() as group:
            a = group.create_task(_await(first))
            b = group.create_task(_await(second))
    except ExceptionGroup as eg:
        raise eg.exceptions[0] from None
    return a.result(), b.result()


async def _await(aw: Awaitable[T]) -> T:
    return await aw


def _labelled(fields: Iterable[FieldMeta]) -> list[Any]:
    return [f.expr.label(f.name) for f in fields]


def _label_key(rel: RelationSpec) -> str:
    return f"_oa_rel_{rel.name}"


def _relation_value(fk: Any, label: Any) -> dict[str, str | None] | None:
    if fk is None:
        return None
    return {"pk": str(to_wire(fk)), "label": None if label is None else str(to_wire(label))}


def _filter(c: CompiledAdmin, stmt: AnySelect, params: ListParams) -> AnySelect:
    """Apply validated filters and search. Raises ``QueryError`` subclasses on bad input."""
    clauses = parse_filters(c.meta, params.filters, allowed=c.filter_allowed)
    if clauses:
        stmt = stmt.where(*(to_sql(clause) for clause in clauses))
    if params.q:
        clause = search_clause(c.search, params.q)
        if clause is not None:
            stmt = stmt.where(clause)
    return stmt
