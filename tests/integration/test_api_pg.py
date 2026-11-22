"""HTTP-level tests of the read API, mounted into a FastAPI app, against real PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from examples.shop.models import Base, Customer, Order, OrderStatus, Product, Tenant
from oneadmin import AdminContext, AdminIdentity, AdminSite, ConfigurationError, ModelAdmin
from oneadmin.core._typing import AnySelect
from tests.conftest import QueryCounter
from tests.models import Staff

pytestmark = pytest.mark.pg

SECRET = "api-test-secret-" + "x" * 32
N_ORDERS = 300


TENANT_PERMISSIONS = frozenset({"customer.*", "order.*", "tenant.view", "product.view"})


class HeaderAuth:
    """Test backend: ``X-Test-User: super`` or ``X-Test-User: tenant:<id>``."""

    async def authenticate(self, request: Any) -> AdminIdentity | None:
        raw = request.headers.get("x-test-user")
        if raw == "super":
            return AdminIdentity(id="1", email="root@example.com", is_superuser=True)
        if raw and raw.startswith("tenant:"):
            tid = int(raw.split(":", 1)[1])
            return AdminIdentity(
                id=f"t{tid}",
                email="t@example.com",
                permissions=TENANT_PERMISSIONS,
                extra={"tenant_id": tid},
            )
        return None


class TenantScoped(ModelAdmin):
    async def get_queryset(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
        tid = ctx.identity.extra.get("tenant_id")
        return stmt if tid is None else stmt.where(self.model.tenant_id == tid)


def build_site(engine: AsyncEngine, secret: str = SECRET) -> AdminSite:
    site = AdminSite(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        secret_key=secret,
        auth_backend=HeaderAuth(),
        title="Shop",
    )

    @site.register(Customer)
    class CustomerAdmin(TenantScoped):
        list_display = ("id", "email", "full_name", "tenant")
        search_fields = ("email", "full_name")
        ordering = ("id",)

    @site.register(Order)
    class OrderAdmin(TenantScoped):
        list_display = ("id", "status", "total", "created_at", "shipped_at", "customer")
        list_filter = ("status", "total", "shipped_at")
        ordering = ("-created_at",)

    site.register(Tenant)
    site.register(Product)
    site.register(Staff)
    return site


@pytest.fixture(scope="module")
async def shop(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    """Committed data: the concurrent count runs on a second connection."""
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(Staff.__table__.create, checkfirst=True)  # type: ignore[attr-defined]
        await conn.execute(insert(Tenant), [{"id": i, "name": f"t{i}"} for i in (1, 2, 3)])
        await conn.execute(
            insert(Customer),
            [
                {"id": i, "tenant_id": 1 + i % 3, "email": f"c{i}@ex.com", "full_name": f"Zoë {i}"}
                for i in range(1, 31)
            ],
        )
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        statuses = list(OrderStatus)
        rows = []
        for i in range(1, N_ORDERS + 1):
            cust = 1 + i % 30
            rows.append(
                {
                    "id": i,
                    "tenant_id": 1 + cust % 3,
                    "customer_id": cust,
                    "status": statuses[i % 4],
                    "total": Decimal(i) / 4,
                    "created_at": t0 + timedelta(minutes=i % 50),  # duplicates on purpose
                    "shipped_at": None if i % 3 == 0 else t0 + timedelta(hours=i),
                }
            )
        # A deliberately inconsistent row: tenant 1 order pointing at a tenant 2 customer.
        rows.append({**rows[0], "id": 9999, "tenant_id": 1, "customer_id": 1})
        await conn.execute(insert(Order), rows)
        await conn.execute(
            insert(Staff),
            [{"id": 1, "email": "s@ex.com", "password_hash": "argon2$...", "api_token": "tok"}],
        )
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(delete(Staff))
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="module")
def site(pg_engine: AsyncEngine) -> AdminSite:
    return build_site(pg_engine)


@pytest.fixture
async def client(shop: None, site: AdminSite) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    site.mount(app, "/admin")  # the sub-app is built once and can be mounted repeatedly
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/admin/api/v1") as c:
        yield c


SUPER = {"x-test-user": "super"}
T1 = {"x-test-user": "tenant:1"}


async def test_requires_authentication(client: httpx.AsyncClient) -> None:
    for path in ("/schema", "/models/order/rows", "/models/order/rows/1"):
        r = await client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "not_authenticated"


async def test_schema_contract(client: httpx.AsyncClient) -> None:
    r = await client.get("/schema", headers=SUPER)
    assert r.status_code == 200
    body = r.json()
    assert body["contract_version"] == 1
    models = {m["slug"]: m for m in body["models"]}
    assert set(models) == {"customer", "order", "tenant", "product", "qe_staff"}
    order = models["order"]
    assert order["list_display"] == [
        "id",
        "status",
        "total",
        "created_at",
        "shipped_at",
        "customer",
    ]
    assert order["default_sort"] == ["-created_at"]
    rel = next(r for r in order["relations"] if r["name"] == "customer")
    assert rel["target"] == "customer"
    fields = {f["name"]: f for f in order["fields"]}
    assert fields["status"]["enum_values"] == ["new", "paid", "shipped", "cancelled"]
    assert "isnull" in fields["shipped_at"]["filter_ops"]
    assert fields["customer_id"]["filter_ops"] == []
    staff = {f["name"] for f in models["qe_staff"]["fields"]}
    assert staff == {"id", "email"}, "password_hash / api_token excluded by default"
    assert models["customer"]["label_field"] == "email"

    etag = r.headers["etag"]
    again = await client.get("/schema", headers={**SUPER, "if-none-match": etag})
    assert again.status_code == 304


async def test_security_headers(client: httpx.AsyncClient) -> None:
    r = await client.get("/schema", headers=SUPER)
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    rows = await client.get("/models/order/rows", headers=SUPER)
    assert rows.headers["cache-control"] == "no-store"


async def test_list_orders_with_labels_and_count(client: httpx.AsyncClient) -> None:
    r = await client.get("/models/order/rows", headers=SUPER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 50
    assert body["pagination"] == "keyset"
    assert body["count"] == {"value": N_ORDERS + 1, "exact": True, "method": "capped"}
    first = body["rows"][0]["values"]
    assert set(first) == {"id", "status", "total", "created_at", "shipped_at", "customer"}
    assert isinstance(first["total"], str), "Decimal is sent as a string"
    assert first["customer"]["label"].startswith("c")
    created = [row["values"]["created_at"] for row in body["rows"]]
    assert created == sorted(created, reverse=True)


async def test_full_walk_via_http(client: httpx.AsyncClient) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": "37", "count": "false", **({"cursor": cursor} if cursor else {})}
        body = (await client.get("/models/order/rows", headers=SUPER, params=params)).json()
        seen.extend(r["pk"] for r in body["rows"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == N_ORDERS + 1


async def test_tenant_scoping_on_list_count_and_detail(
    client: httpx.AsyncClient, pg_engine: AsyncEngine
) -> None:
    async with AsyncSession(pg_engine) as s:
        expected = (
            await s.execute(select(func.count()).select_from(Order).where(Order.tenant_id == 1))
        ).scalar_one()
        other = (
            await s.execute(select(Order.id).where(Order.tenant_id == 2).limit(1))
        ).scalar_one()
    body = (await client.get("/models/order/rows", headers=T1, params={"limit": 500})).json()
    assert body["count"]["value"] == expected == len(body["rows"])

    assert (await client.get(f"/models/order/rows/{other}", headers=T1)).status_code == 404
    assert (await client.get(f"/models/order/rows/{other}", headers=SUPER)).status_code == 200
    exact = (await client.get("/models/order/count", headers=T1)).json()
    assert exact == {"value": expected, "exact": True, "method": "exact"}


async def test_fk_label_respects_target_scope(client: httpx.AsyncClient) -> None:
    """Tenant 1 may see order 9999, but not the tenant-2 customer it points at."""
    r = await client.get("/models/order/rows/9999", headers=T1)
    assert r.status_code == 200
    assert r.json()["values"]["customer"] == {"pk": "1", "label": None}
    r = await client.get("/models/order/rows/9999", headers=SUPER)
    assert r.json()["values"]["customer"] == {"pk": "1", "label": "c1@ex.com"}


async def test_detail_excludes_sensitive_fields(client: httpx.AsyncClient) -> None:
    r = await client.get("/models/qe_staff/rows/1", headers=SUPER)
    assert r.json()["values"] == {"id": 1, "email": "s@ex.com"}


async def test_filters_and_search(client: httpx.AsyncClient) -> None:
    body = (
        await client.get(
            "/models/order/rows",
            headers=SUPER,
            params={"f.status__in": "paid,shipped", "f.shipped_at__isnull": "true", "limit": 500},
        )
    ).json()
    assert body["rows"]
    assert {r["values"]["status"] for r in body["rows"]} <= {"paid", "shipped"}
    assert all(r["values"]["shipped_at"] is None for r in body["rows"])

    found = (
        await client.get("/models/customer/rows", headers=SUPER, params={"q": "zoë 17"})
    ).json()
    assert [r["pk"] for r in found["rows"]] == ["17"]


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"sort": "notes"}, "invalid_sort"),  # exists, but not sortable
        ({"sort": "id; DROP TABLE tenant"}, "invalid_sort"),
        ({"f.customer_id": "1"}, "invalid_filter"),  # not in list_filter
        ({"f.total__gte": "1 OR 1=1"}, "invalid_filter"),
        ({"cursor": "garbage"}, "invalid_cursor"),
        ({"limit": "0"}, "invalid_request"),
        ({"q": "x" * 201}, "invalid_request"),
    ],
)
async def test_bad_params_are_400(
    client: httpx.AsyncClient, params: dict[str, str], code: str
) -> None:
    r = await client.get("/models/order/rows", headers=SUPER, params=params)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == code


async def test_unknown_model_and_route(client: httpx.AsyncClient) -> None:
    r = await client.get("/models/nope/rows", headers=SUPER)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "unknown_model")
    r = await client.get("/nope", headers=SUPER)
    assert r.status_code == 404
    r = await client.get("/models/order/rows/not-an-int", headers=SUPER)
    assert r.status_code == 404


async def test_one_statement_per_page(
    client: httpx.AsyncClient, count_queries: QueryCounter
) -> None:
    await client.get("/models/order/rows", headers=SUPER, params={"count": "false"})
    count_queries.reset()
    r = await client.get("/models/order/rows", headers=SUPER, params={"count": "false"})
    assert r.status_code == 200
    selects = [s for s in count_queries.statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, count_queries.statements


async def test_cursor_from_another_site_is_rejected(
    client: httpx.AsyncClient, pg_engine: AsyncEngine
) -> None:
    body = (await client.get("/models/order/rows", headers=SUPER)).json()
    other = build_site(pg_engine, secret="another-site-secret-" + "y" * 32)
    app = FastAPI()
    other.mount(app, "/other")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/other/api/v1"
    ) as c:
        r = await c.get("/models/order/rows", headers=SUPER, params={"cursor": body["next_cursor"]})
    assert r.json()["error"]["code"] == "invalid_cursor"


def test_configuration_errors_are_actionable(pg_engine: AsyncEngine) -> None:
    def site_with(admin_cls: type[ModelAdmin]) -> AdminSite:
        s = AdminSite(
            session_factory=async_sessionmaker(pg_engine),
            secret_key=SECRET,
            auth_backend=HeaderAuth(),
        )
        s.register(Order, admin_cls)
        return s

    class Bad1(ModelAdmin):
        list_display = ("id", "nope")

    class Bad2(ModelAdmin):
        list_display = ("lines",)  # one-to-many

    class Bad3(ModelAdmin):
        ordering = ("-missing",)

    for cls, msg in [
        (Bad1, "neither a column nor a relationship"),
        (Bad2, "only many-to-one"),
        (Bad3, "Available:"),
    ]:
        with pytest.raises(ConfigurationError, match=msg):
            site_with(cls).build_app()
    with pytest.raises(ConfigurationError, match="at least 32"):
        AdminSite(session_factory=async_sessionmaker(pg_engine), secret_key="short")


async def test_user_attributes_do_not_collide_with_internals(pg_engine: AsyncEngine) -> None:
    """Users may name their own attributes anything; compiled state lives elsewhere."""

    class CustomerAdmin(ModelAdmin):
        label = "my own attribute"
        search = "also mine"
        meta = ("anything",)
        list_display = ("id", "email")

    site = AdminSite(
        session_factory=async_sessionmaker(pg_engine), secret_key=SECRET, auth_backend=HeaderAuth()
    )
    site.register(Customer, CustomerAdmin)
    site.build_app()
    [admin] = site.admins()
    assert admin.compiled.label.name == "email"
    assert admin.label == "my own attribute"  # type: ignore[attr-defined]
