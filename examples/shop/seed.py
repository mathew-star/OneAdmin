"""Seed the example shop with deterministic, set-based data (PostgreSQL only).

    uv run python -m examples.shop.seed --dsn postgresql+asyncpg://... --orders 1000000

Rows are generated server-side from ``generate_series``, so seeding 1M orders takes seconds.
The data is deterministic (derived from the series value), which keeps benchmarks
reproducible:
- about one third of orders have ``shipped_at IS NULL``, which exercises nullable-sort
  pagination
- ``created_at`` has many duplicates, which exercises the PK tiebreak
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from sqlalchemy import ColumnElement, Text, case, cast, func, insert, literal, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from examples.shop.models import Base, Category, Customer, Order, OrderStatus, Product, Tenant

EPOCH = "2026-01-01T00:00:00Z"


def _series(n: int) -> Any:
    return func.generate_series(1, n).table_valued("value").render_derived(name="g")


def _txt(expr: ColumnElement[Any]) -> ColumnElement[str]:
    return cast(expr, Text)


async def seed(
    engine: AsyncEngine, *, tenants: int = 3, customers: int = 50_000, orders: int = 1_000_000
) -> dict[str, float]:
    """Drop and recreate the example schema, then fill it. Returns phase timings in seconds."""
    timings: dict[str, float] = {}
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

        t0 = time.perf_counter()
        g = _series(tenants)
        await conn.execute(
            insert(Tenant).from_select(
                ["id", "name"], select(g.c.value, "tenant-" + _txt(g.c.value))
            )
        )
        g = _series(customers)
        await conn.execute(
            insert(Customer).from_select(
                ["id", "tenant_id", "email", "full_name"],
                select(
                    g.c.value,
                    1 + g.c.value % tenants,
                    "customer" + _txt(g.c.value) + "@example.com",
                    "Customer " + _txt(g.c.value),
                ),
            )
        )
        g = _series(20)
        await conn.execute(
            insert(Category).from_select(
                ["id", "tenant_id", "name"],
                select(g.c.value, 1 + g.c.value % tenants, "Category " + _txt(g.c.value)),
            )
        )
        g = _series(2_000)
        await conn.execute(
            insert(Product).from_select(
                ["id", "tenant_id", "sku", "name", "price", "attributes", "category_id"],
                select(
                    g.c.value,
                    1 + g.c.value % tenants,
                    "SKU-" + _txt(g.c.value),
                    "Product " + _txt(g.c.value),
                    (g.c.value % 500) + 0.99,
                    func.jsonb_build_object("color", "c" + _txt(g.c.value % 7)),
                    1 + g.c.value % 20,
                ),
            )
        )
        timings["dimensions_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        g = _series(orders)
        statuses = list(OrderStatus)
        status = case(
            *((g.c.value % len(statuses) == i, literal(s.value)) for i, s in enumerate(statuses))
        )
        epoch = cast(literal(EPOCH), Order.__table__.c.created_at.type)
        await conn.execute(
            insert(Order).from_select(
                ["id", "tenant_id", "customer_id", "status", "total", "created_at", "shipped_at"],
                select(
                    g.c.value,
                    # tenant must match the customer's tenant
                    1 + (1 + g.c.value % customers) % tenants,
                    1 + g.c.value % customers,
                    cast(status, Order.__table__.c.status.type),
                    (g.c.value % 10_000) / 7.0,
                    epoch + func.make_interval(0, 0, 0, 0, 0, g.c.value % 200_000),
                    case(
                        (g.c.value % 3 == 0, None),
                        else_=epoch + func.make_interval(0, 0, 0, 0, g.c.value % 5_000),
                    ),
                ),
            )
        )
        timings["orders_s"] = time.perf_counter() - t0
        for table, n in (("customer", customers), ("order", orders), ("product", 2_000)):
            await conn.execute(
                select(func.setval(func.pg_get_serial_sequence(f'"{table}"', "id"), n))
            )

    # ANALYZE outside the transaction so planner statistics (and reltuples) are realistic.
    async with engine.connect() as conn:
        auto = await conn.execution_options(isolation_level="AUTOCOMMIT")
        t0 = time.perf_counter()
        await auto.execute(text("ANALYZE"))
        timings["analyze_s"] = time.perf_counter() - t0
    return timings


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed the OneAdmin example shop (PostgreSQL)")
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--orders", type=int, default=1_000_000)
    parser.add_argument("--customers", type=int, default=50_000)
    args = parser.parse_args()
    engine = create_async_engine(args.dsn)
    try:
        timings = await seed(engine, customers=args.customers, orders=args.orders)
    finally:
        await engine.dispose()
    print({k: round(v, 2) for k, v in timings.items()})


if __name__ == "__main__":
    asyncio.run(_main())
