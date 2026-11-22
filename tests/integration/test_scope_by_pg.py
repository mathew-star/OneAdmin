"""``conventions.scope_by``: one line of configuration isolates tenants on every path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from examples.shop.models import Base, Customer, Order, OrderStatus, Tenant
from oneadmin import AdminContext, AdminIdentity, AdminSite, ModelAdmin
from oneadmin import conventions as cv
from oneadmin.auth import migrate
from oneadmin.core._typing import AnySelect

pytestmark = pytest.mark.pg


def tenant_of(ctx: AdminContext) -> Any:
    """Superusers see everything; everyone else only their tenant(s), or nothing."""
    return cv.ALL if ctx.identity.is_superuser else ctx.identity.extra.get("tenant_id")


class HeaderAuth:
    """``X-Tenant``: ``super``, ``none``, or a tenant id / comma-separated ids."""

    async def authenticate(self, request: Any) -> AdminIdentity | None:
        raw = request.headers.get("x-tenant")
        if raw is None:
            return None
        if raw == "super":
            return AdminIdentity(id="0", email="root@ex.com", is_superuser=True)
        tenant: Any = None if raw == "none" else [int(t) for t in raw.split(",")]
        if isinstance(tenant, list) and len(tenant) == 1:
            tenant = tenant[0]
        return AdminIdentity(
            id=raw,
            email=f"{raw}@ex.com",
            permissions=frozenset({"customer.*", "order.*"}),
            extra={"tenant_id": tenant},
        )


class OrderAdmin(ModelAdmin[Order]):
    list_display = (Order.id, Order.customer)

    async def get_queryset(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
        return stmt.where(Order.status != OrderStatus.CANCELLED)  # composes with the scope


@pytest.fixture(scope="module")
async def schema(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await migrate.upgrade(pg_engine)
    yield
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await migrate.downgrade(pg_engine, "base")


@pytest.fixture
async def client(schema: None, pg_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with pg_engine.begin() as conn:
        await conn.execute(text('TRUNCATE "order", customer, tenant, oneadmin_audit_log CASCADE'))
        await conn.execute(text("INSERT INTO tenant (id, name) VALUES (1, 't1'), (2, 't2')"))
        await conn.execute(
            text(
                "INSERT INTO customer (id, tenant_id, email, full_name) VALUES "
                "(1, 1, 'a@t1', 'A'), (2, 2, 'b@t2', 'B')"
            )
        )
        await conn.execute(
            text(
                'INSERT INTO "order" (id, tenant_id, customer_id, status, total, created_at) VALUES '
                "(1, 1, 1, 'new', 1, now()), (2, 2, 2, 'new', 2, now()), "
                "(3, 1, 1, 'cancelled', 3, now())"
            )
        )
        for table in ("customer", '"order"'):  # explicit ids above: move the sequences past them
            await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), 100)"))
    site = AdminSite(
        session_factory=async_sessionmaker(pg_engine, expire_on_commit=False),
        secret_key="scope-test-secret-" + "s" * 32,
        auth_backend=HeaderAuth(),
        conventions=[cv.scope_by("tenant_id", tenant_of)],
    )
    site.register(Customer)
    site.register(Order, OrderAdmin)
    site.register(Tenant)
    app = FastAPI()
    site.mount(app, "/admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test/admin/api/v1",
        headers={"origin": "http://test"},
    ) as c:
        yield c


async def pks(client: httpx.AsyncClient, model: str, tenant: str) -> list[str]:
    r = await client.get(
        f"/models/{model}/rows", params={"sort": "id"}, headers={"x-tenant": tenant}
    )
    assert r.status_code == 200, r.text
    return [row["pk"] for row in r.json()["rows"]]


async def test_reads_are_scoped_and_compose_with_get_queryset(client: httpx.AsyncClient) -> None:
    assert await pks(client, "customer", "1") == ["1"]
    assert await pks(client, "order", "1") == ["1"], "tenant scope AND get_queryset"
    assert await pks(client, "order", "super") == ["1", "2"]
    assert await pks(client, "order", "1,2") == ["1", "2"], "a collection means any of these"
    detail = await client.get("/models/customer/rows/2", headers={"x-tenant": "1"})
    assert detail.status_code == 404


async def test_a_missing_scope_value_fails_closed(client: httpx.AsyncClient) -> None:
    assert await pks(client, "customer", "none") == []
    count = await client.get("/models/customer/count", headers={"x-tenant": "none"})
    assert count.json()["value"] == 0


async def test_create_autofills_the_scope_column(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/models/customer/rows",
        json={"email": "new@t1", "full_name": "New"},
        headers={"x-tenant": "1"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["values"]["tenant_id"] == 1


async def test_writes_cannot_cross_the_scope(client: httpx.AsyncClient) -> None:
    other = await client.post(
        "/models/customer/rows",
        json={"tenant_id": 2, "email": "x@t2", "full_name": "X"},
        headers={"x-tenant": "1"},
    )
    assert (other.status_code, other.json()["error"]["code"]) == (403, "out_of_scope")
    update = await client.patch(
        "/models/customer/rows/2",
        json={"full_name": "Hacked"},
        headers={"x-tenant": "1", "if-match": "x"},
    )
    assert update.status_code == 404
    v = (await client.get("/models/order/rows/1", headers={"x-tenant": "1"})).json()["version"]
    repoint = await client.patch(
        "/models/order/rows/1", json={"customer_id": 2}, headers={"x-tenant": "1", "if-match": v}
    )
    assert repoint.json()["error"]["fields"] == {"customer_id": "no Customer with this key"}


async def test_labels_of_out_of_scope_rows_stay_hidden(client: httpx.AsyncClient) -> None:
    r = await client.get("/models/order/rows", params={"sort": "id"}, headers={"x-tenant": "super"})
    labels = {row["pk"]: row["values"]["customer"]["label"] for row in r.json()["rows"]}
    assert labels == {"1": "a@t1", "2": "b@t2"}, "a superuser sees every label"
    r = await client.get("/models/order/rows", params={"sort": "id"}, headers={"x-tenant": "2"})
    assert [row["values"]["customer"]["label"] for row in r.json()["rows"]] == ["b@t2"]
