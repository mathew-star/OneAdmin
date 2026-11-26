"""Row-count strategies (ADR-0004).

* ``exact``: ``count(*)`` over the filtered statement.
* ``capped``: ``count(*)`` over ``LIMIT cap + 1``. Reports ``cap+`` when it hits the cap.
* ``estimate``: PostgreSQL ``pg_class.reltuples``. Only valid for an *unfiltered,
  unscoped* statement. Otherwise a tenant-scoped admin would learn the global row count
  (an information leak), so it degrades to ``capped``.
* ``auto``: estimate when allowed and above ``estimate_threshold``, else capped.
* ``none``: don't count.

On PostgreSQL, counting runs under ``SET LOCAL statement_timeout``. A timeout yields
``Count(value=None)`` rather than an error, because a slow count must never break the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import column, table

from oneadmin.core._typing import AnySelect

Strategy = Literal["auto", "exact", "capped", "estimate", "none"]
CountMethod = Literal["exact", "capped", "estimate", "timeout", "none"]
"""How a count was produced. ``capped`` may still be exact when the cap wasn't reached."""

_pg_class = table("pg_class", column("oid"), column("reltuples"))


@dataclass(frozen=True, slots=True)
class Count:
    value: int | None
    exact: bool
    """True if ``value`` is the precise number. False if it is a lower bound or an estimate."""
    method: CountMethod


async def count_rows(
    session: AsyncSession,
    stmt: AnySelect,
    *,
    strategy: Strategy = "auto",
    cap: int = 10_000,
    estimate_threshold: int = 100_000,
    qualified_table: str | None = None,
    timeout_ms: int | None = 1_500,
) -> Count:
    """Count rows of ``stmt`` (a scoped, filtered SELECT without ORDER BY or LIMIT).

    ``qualified_table`` (``"schema.table"`` or ``"table"``) enables estimates. Pass it only
    when ``stmt`` has no WHERE clause at all.
    """
    if strategy == "none":
        return Count(None, exact=False, method="none")
    dialect = session.get_bind().dialect.name
    is_pg = dialect == "postgresql"
    unfiltered = stmt.whereclause is None
    if strategy in ("estimate", "auto") and is_pg and unfiltered and qualified_table:
        estimate = await _estimate(session, qualified_table)
        if estimate is not None and (strategy == "estimate" or estimate >= estimate_threshold):
            return Count(estimate, exact=False, method="estimate")
    if strategy == "auto":
        strategy = "capped"
    if strategy == "estimate":
        strategy = "capped"

    inner = stmt.order_by(None)
    if strategy == "capped":
        inner = inner.limit(cap + 1)
    query = select(func.count()).select_from(inner.subquery())
    try:
        # Savepoint: a timeout aborts only the savepoint, and SET LOCAL is reverted with it.
        async with session.begin_nested():
            prev: str | None = None
            if is_pg and timeout_ms is not None:
                prev = (
                    await session.execute(select(func.current_setting("statement_timeout")))
                ).scalar_one()
                await session.execute(
                    select(func.set_config("statement_timeout", f"{int(timeout_ms)}ms", True))
                )
            n = int((await session.execute(query)).scalar_one())
            if prev is not None:
                await session.execute(select(func.set_config("statement_timeout", prev, True)))
    except DBAPIError as exc:
        if is_pg and _is_timeout(exc):
            return Count(None, exact=False, method="timeout")
        raise
    if strategy == "capped" and n > cap:
        return Count(cap, exact=False, method="capped")
    return Count(n, exact=True, method=strategy)


async def _estimate(session: AsyncSession, qualified_table: str) -> int | None:
    value = (
        await session.execute(
            select(_pg_class.c.reltuples).where(
                _pg_class.c.oid == func.to_regclass(qualified_table)
            )
        )
    ).scalar_one_or_none()
    if value is None or value < 0:  # -1: never vacuumed/analyzed (PG14+)
        return None
    return int(value)


def _is_timeout(exc: DBAPIError) -> bool:
    orig = exc.orig
    return "statement timeout" in str(orig).lower()
