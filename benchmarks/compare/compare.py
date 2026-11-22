"""Head-to-head list-page latency: OneAdmin vs sqladmin vs Starlette-Admin.

Same PostgreSQL database, same seeded data (the ``oneadmin demo`` shop), same machine, all
three admins mounted in one FastAPI app and called in-process (``httpx.ASGITransport``), so
the numbers include each library's whole request path (query building, SQL, rendering or
JSON encoding) but no network.

    uv run --with sqladmin==0.32.0 --with starlette-admin==1.0.3 \\
        python benchmarks/compare/compare.py --dsn postgresql+asyncpg://... --rows 1000000

Pages, all sorted by ``created_at`` descending, 50 rows:
- **first**: page 1
- **middle**: rows rows/2 .. rows/2+50 (``?page=`` for sqladmin and Starlette-Admin, and
  OneAdmin a real cursor at that depth, as the UI would hold after paging there)
- **last**: the final page

Each library is measured as it ships, with its defaults (sqladmin and Starlette-Admin count
exactly on every request; OneAdmin uses its capped/estimated count). Authentication is off in
all three. Results print as a Markdown table plus JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import re
import statistics
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oneadmin import AdminIdentity, AdminSite, ModelAdmin
from oneadmin.core.query.cursor import Cursor
from oneadmin.core.query.sorting import parse_sort
from oneadmin.demo.models import Base, Category, Customer, Order, Product
from oneadmin.demo.seed import seed

PAGE = 50
COLUMNS = ("id", "customer", "product", "quantity", "status", "total", "created_at")


class EveryoneIsRoot:
    async def authenticate(self, request: Any) -> AdminIdentity:
        return AdminIdentity(id="1", email="bench@example.com", is_superuser=True)


def build_app(engine: AsyncEngine) -> tuple[FastAPI, AdminSite]:
    app = FastAPI()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    site = AdminSite(session_factory=sessions, secret_key="b" * 32, auth_backend=EveryoneIsRoot())

    @site.register(Order)
    class OrderAdmin(ModelAdmin[Order]):
        list_display = COLUMNS
        ordering = (Order.created_at.desc(),)
        list_per_page = PAGE

    # The same admin with exact counts, like the other two libraries compute on every page.
    @site.register(Order)
    class ExactCountOrderAdmin(OrderAdmin):
        name = "demo_order_exact"
        count_strategy = "exact"

    site.mount(app, "/oneadmin")

    from sqladmin import Admin, ModelView  # noqa: PLC0415

    class OrderView(ModelView, model=Order):  # type: ignore[call-arg,misc]
        column_list = [getattr(Order, c) for c in COLUMNS]
        column_default_sort = [(Order.created_at, True)]
        page_size = PAGE

    sqladmin = Admin(app, engine, base_url="/sqladmin")
    sqladmin.add_view(OrderView)

    from starlette_admin.contrib.sqla import Admin as SAdmin  # noqa: PLC0415
    from starlette_admin.contrib.sqla import ModelView as SView  # noqa: PLC0415

    sadmin = SAdmin(engine, base_url="/starlette-admin")
    # Starlette-Admin requires a view for every related model.
    for model, key in ((Category, "category"), (Customer, "customer"), (Product, "product")):
        sadmin.add_view(SView(model, key=key))
    sadmin.add_view(SView(Order, key="order"))
    sadmin.mount_to(app)
    return app, site


async def oneadmin_cursor(site: AdminSite, slug: str, engine: AsyncEngine, depth: int) -> str:
    """A genuine cursor at ``depth``: the values of the row before it, signed by the site."""
    admin = site.admin_by_slug(slug)
    if admin is None:
        raise LookupError(slug)
    c = admin.compiled
    sort = parse_sort(c.meta, None, allowed=c.sort_allowed, default=c.default_sort)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(Order.created_at, Order.id)
                .order_by(Order.created_at.desc(), Order.id.desc())
                .offset(depth - 1)
                .limit(1)
            )
        ).one()
    return site.service._codec.encode(sort, Cursor("after", tuple(row)))


def first_id(body: str, url: str) -> int:
    """The id of the first row a list response shows (JSON for OneAdmin, HTML otherwise)."""
    if "/oneadmin/" in url:
        return int(json.loads(body)["rows"][0]["pk"])
    ids = [int(m) for m in re.findall(r"/order/(?:details|detail)(?:/|\?pk=)(\d+)", body)]
    if not ids:
        raise AssertionError(f"no row links found in {url}")
    return ids[0]


async def measure(call: Callable[[], Awaitable[httpx.Response]], repeat: int) -> dict[str, float]:
    await call()  # warm-up (plans, caches)
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        r = await call()
        samples.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
    samples.sort()
    return {
        "p50": round(statistics.median(samples), 1),
        "p95": round(
            samples[min(len(samples), math.ceil(len(samples) * 0.95)) - 1], 1
        ),  # nearest rank
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()

    engine = create_async_engine(args.dsn, pool_size=10)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        have = (await conn.execute(select(func.count()).select_from(Order))).scalar_one()
    if have != args.rows:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with engine.begin() as conn:
            await seed(conn, args.rows)
        async with engine.connect() as conn:
            await (await conn.execution_options(isolation_level="AUTOCOMMIT")).exec_driver_sql(
                "VACUUM ANALYZE"
            )

    app, site = build_app(engine)
    mid = args.rows // 2
    last_page = (args.rows + PAGE - 1) // PAGE
    cursor = await oneadmin_cursor(site, "demo_order", engine, mid)
    cursor_exact = await oneadmin_cursor(site, "demo_order_exact", engine, mid)
    sa = f"page_size={PAGE}&sort=created_at__desc"
    cases: dict[str, dict[str, str]] = {
        "OneAdmin": {
            "first": "/oneadmin/api/v1/models/demo_order/rows",
            "middle": f"/oneadmin/api/v1/models/demo_order/rows?cursor={cursor}",
            "last": "/oneadmin/api/v1/models/demo_order/rows?last=true",
        },
        "OneAdmin, exact counts": {
            "first": "/oneadmin/api/v1/models/demo_order_exact/rows",
            "middle": f"/oneadmin/api/v1/models/demo_order_exact/rows?cursor={cursor_exact}",
            "last": "/oneadmin/api/v1/models/demo_order_exact/rows?last=true",
        },
        "sqladmin 0.32": {
            "first": "/sqladmin/order/list?page=1",
            "middle": f"/sqladmin/order/list?page={mid // PAGE + 1}",
            "last": f"/sqladmin/order/list?page={last_page}",
        },
        "Starlette-Admin 1.0": {
            "first": f"/starlette-admin/order/list?page=1&{sa}",
            "middle": f"/starlette-admin/order/list?page={mid // PAGE + 1}&{sa}",
            "last": f"/starlette-admin/order/list?page={last_page}&{sa}",
        },
    }
    # Created_at increases with the id, so the expected first row at each depth is known.
    expected = {
        "first": args.rows,
        "middle": args.rows - mid,
        "last": args.rows - (last_page - 1) * PAGE,
    }
    results: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", timeout=120
    ) as client:
        for lib, pages in cases.items():
            results[lib] = {}
            for name, url in pages.items():
                got = first_id((await client.get(url)).text, url)
                if got != expected[name]:  # never time a page that returns the wrong rows
                    raise AssertionError(
                        f"{lib} {name}: first row {got}, expected {expected[name]}"
                    )
                results[lib][name] = await measure(partial(client.get, url), args.repeat)

    print(
        f"\n{args.rows:,} orders, PostgreSQL, {platform.processor() or platform.machine()}, "
        f"Python {platform.python_version()}; p50 / p95 ms over {args.repeat} requests\n"
    )
    print("| Library | First page | Middle page | Last page |")
    print("|---|---|---|---|")
    for lib, timings in results.items():
        cells = [f"{timings[p]['p50']} / {timings[p]['p95']}" for p in ("first", "middle", "last")]
        print(f"| {lib} | " + " | ".join(cells) + " |")
    print("\n" + json.dumps({"rows": args.rows, "results": results}, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
