"""List-page latency on the example shop (seed it first with examples.shop.seed).

    uv run python -m examples.shop.seed --dsn $DSN --orders 1000000
    uv run python benchmarks/bench_list.py --dsn $DSN

Measures wall-clock time (Python → asyncpg → PG → rows) for one 50-row page at increasing
depth, in OneAdmin keyset mode versus OFFSET, the strategy sqladmin and Starlette-Admin use
(verified in their source; see docs/research/landscape.md). It also times count strategies.
This is not a cross-library benchmark (that's M7): it isolates the query strategy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from examples.shop.models import Order
from oneadmin.core._typing import AnySelect
from oneadmin.core.meta import introspect
from oneadmin.core.query.counting import count_rows
from oneadmin.core.query.cursor import CursorCodec
from oneadmin.core.query.paginate import fetch_page
from oneadmin.core.query.sorting import parse_sort

META = introspect(Order)
CODEC = CursorCodec("benchmark-secret-0123456789abcdef")
LIMIT = 50


def cols(tenant: int | None) -> AnySelect:
    stmt = select(Order.id, Order.status, Order.total, Order.created_at, Order.shipped_at)
    return stmt.where(Order.tenant_id == tenant) if tenant is not None else stmt


async def timeit(fn: Any, repeat: int) -> dict[str, float]:
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
    }


async def cursor_at(session: AsyncSession, stmt: AnySelect, spec: str, depth: int) -> str | None:
    """Build a real cursor at ``depth`` by walking to it with one OFFSET query (setup only)."""
    sort = parse_sort(META, spec, allowed=META.fields.keys())
    if depth == 0:
        return None
    from oneadmin.core.query.cursor import Cursor  # noqa: PLC0415

    row = (
        await session.execute(
            stmt.with_only_columns(*(k.field.expr for k in sort.keys))
            .order_by(*sort.order_by())
            .offset(depth - 1)
            .limit(1)
        )
    ).one()
    return CODEC.encode(sort, Cursor("after", tuple(row)))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--repeat", type=int, default=30)
    args = ap.parse_args()
    engine = create_async_engine(args.dsn, pool_size=2)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    results: list[dict[str, Any]] = []
    async with sm() as s:
        total = (await s.execute(select(func.count()).select_from(Order))).scalar_one()
        version = (await s.execute(select(func.version()))).scalar_one()
        for spec, tenant in [("-created_at", None), ("-shipped_at", None), ("-created_at", 2)]:
            sort = parse_sort(META, spec, allowed=META.fields.keys())
            stmt = cols(tenant)
            for depth in (0, 10_000, 100_000, 300_000):
                token = await cursor_at(s, stmt, spec, depth)

                async def keyset(
                    token: str | None = token, stmt: AnySelect = stmt, sort: Any = sort
                ) -> None:
                    await fetch_page(s, stmt, sort, CODEC, limit=LIMIT, cursor=token)

                async def offset(
                    depth: int = depth, stmt: AnySelect = stmt, sort: Any = sort
                ) -> None:
                    q = stmt.order_by(*sort.order_by()).offset(depth).limit(LIMIT)
                    (await s.execute(q)).all()

                await keyset()
                await offset()  # warm caches for both
                k = await timeit(keyset, args.repeat)
                o = await timeit(offset, args.repeat)
                results.append(
                    {"sort": spec, "tenant": tenant, "depth": depth, "keyset": k, "offset": o}
                )
                print(json.dumps(results[-1]))

        counts = {}
        for name, stmt, kw in [
            ("exact_unfiltered", cols(None), {"strategy": "exact"}),
            ("auto_unfiltered", cols(None), {"strategy": "auto", "qualified_table": '"order"'}),
            ("exact_tenant", cols(2), {"strategy": "exact"}),
            ("auto_tenant(capped)", cols(2), {"strategy": "auto"}),
        ]:

            async def run(stmt: AnySelect = stmt, kw: dict[str, Any] = kw) -> None:
                await count_rows(s, stmt, **kw)

            await run()
            counts[name] = await timeit(run, args.repeat)
            print(name, counts[name])
    await engine.dispose()
    print(
        json.dumps(
            {"rows": total, "pg": version.split(",")[0], "python": platform.python_version()}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
