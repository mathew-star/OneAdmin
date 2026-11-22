"""``oneadmin demo``: seeding is deterministic and correct on SQLite and PostgreSQL, and the
served app works with the printed login."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from oneadmin.auth import migrate
from oneadmin.cli import Console
from oneadmin.cli.demo import DEMO_EMAIL, DEMO_PASSWORD, prepare
from oneadmin.demo.models import Base, Customer, Order, OrderStatus
from oneadmin.demo.seed import customers_for

ROWS = 2_000


async def login(app: Any) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1/admin/api/v1"
    )
    r = await client.post(
        "/auth/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        headers={"origin": "http://127.0.0.1"},
    )
    assert r.status_code == 200, r.text
    client.headers["cookie"] = f"oneadmin_session={r.cookies['oneadmin_session']}"
    return client


async def check_seeded(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        orders = (await conn.execute(select(func.count()).select_from(Order))).scalar_one()
        customers = (await conn.execute(select(func.count()).select_from(Customer))).scalar_one()
        statuses = dict(
            (await conn.execute(select(Order.status, func.count()).group_by(Order.status))).all()
        )
    assert (orders, customers) == (ROWS, customers_for(ROWS))
    assert statuses == {
        OrderStatus.CANCELLED: 200, OrderStatus.NEW: 600, OrderStatus.PAID: 600, OrderStatus.SHIPPED: 600,
    }  # fmt: skip


async def check_app(app: Any) -> None:
    c = await login(app)
    try:
        first = (await c.get("/models/demo_order/rows")).json()
        last = (await c.get("/models/demo_order/rows", params={"last": "true"})).json()
        assert first["rows"][0]["pk"] == str(ROWS), "newest first"
        assert last["rows"][-1]["pk"] == "1"
        assert first["rows"][0]["values"]["customer"]["label"].startswith("Customer ")
        # Walk two keyset pages: seeded timestamps must compare correctly with cursors.
        page2 = (
            await c.get("/models/demo_order/rows", params={"cursor": first["next_cursor"]})
        ).json()
        assert int(page2["rows"][0]["pk"]) == ROWS - 50
        shipped = await c.get(
            "/models/demo_order/rows", params={"f.status__eq": "shipped", "sort": "-total"}
        )
        assert shipped.status_code == 200
        assert {r["values"]["status"] for r in shipped.json()["rows"]} == {"shipped"}
    finally:
        await c.aclose()


async def test_demo_on_sqlite(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'demo.db'}"
    con = Console(stdout=io.StringIO())
    app = await prepare(url, ROWS, con)
    assert "Seeding 2,000 orders" in con.stdout.getvalue()  # type: ignore[attr-defined]
    engine = create_async_engine(url)
    try:
        await check_seeded(engine)
    finally:
        await engine.dispose()
    await check_app(app)
    again = Console(stdout=io.StringIO())
    await prepare(url, ROWS, again)
    assert "Using the existing demo database (2,000 orders)" in again.stdout.getvalue()  # type: ignore[attr-defined]


@pytest.mark.pg
async def test_demo_on_postgres(pg_engine: AsyncEngine, pg_url: str) -> None:
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    try:
        app = await prepare(pg_url, ROWS, Console(stdout=io.StringIO()))
        await check_seeded(pg_engine)
        await check_app(app)
    finally:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await migrate.downgrade(pg_engine, "base")
