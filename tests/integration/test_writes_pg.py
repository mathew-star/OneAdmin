"""Writes over HTTP against real PostgreSQL (ADR-0018, ADR-0019, threat model E1/T2).

Two tenants share the tables. ``get_queryset`` scopes everything by tenant, and the tests
attack that boundary from every direction a write can take.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from examples.shop.models import Base, Customer, Order, OrderStatus, Product, Tenant
from oneadmin import (
    AdminContext,
    AdminIdentity,
    AdminSite,
    ModelAdmin,
    ValidationError,
    action,
)
from oneadmin.auth import migrate
from oneadmin.auth import tables as t
from oneadmin.core._typing import AnySelect
from tests.models import Staff

pytestmark = pytest.mark.pg

# Explicit order permissions (not ``order.*``, which would include the custom "refund").
TENANT_PERMS = frozenset(
    {
        "customer.*",
        "order.view",
        "order.add",
        "order.change",
        "order.delete",
        "product.*",
        "tenant.view",
    }
)
VIEWER_PERMS = frozenset({"customer.view", "order.view"})


class HeaderAuth:
    """``X-Test-User``: ``super``, ``tenant:<id>`` (full access to its tenant) or
    ``viewer:<id>`` (read-only on customers and orders)."""

    async def authenticate(self, request: Any) -> AdminIdentity | None:
        raw = request.headers.get("x-test-user", "")
        if raw == "super":
            return AdminIdentity(id="1", email="root@example.com", is_superuser=True)
        role, _, tid = raw.partition(":")
        if role in ("tenant", "viewer") and tid.isdigit():
            perms = TENANT_PERMS if role == "tenant" else VIEWER_PERMS
            return AdminIdentity(
                id=f"{role}{tid}",
                email=f"{role}{tid}@example.com",
                permissions=perms,
                extra={"tenant_id": int(tid)},
            )
        return None


class TenantScoped(ModelAdmin):
    async def get_queryset(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
        tid = ctx.identity.extra.get("tenant_id")
        return stmt if tid is None else stmt.where(self.model.tenant_id == tid)


class CustomerAdmin(TenantScoped):
    list_display = ("id", "email", "full_name", "tenant")

    async def clean(
        self, ctx: AdminContext, data: dict[str, Any], obj: Any | None
    ) -> dict[str, Any]:
        if "email" in data and "@" not in data["email"]:
            raise ValidationError({"email": "must be an email address"})
        if "email" in data:
            data["email"] = data["email"].lower()
        return data


class OrderAdmin(TenantScoped):
    list_display = ("id", "status", "total", "customer")
    readonly_fields = ("created_at",)

    async def before_delete(self, ctx: AdminContext, obj: Any) -> None:
        if obj.status is OrderStatus.PAID:
            raise ValidationError("Paid orders can't be deleted.")

    @action(label="Mark paid", confirm="Mark the selected orders as paid?")
    async def mark_paid(self, ctx: AdminContext, rows: list[Order]) -> str:
        for order in rows:
            order.status = OrderStatus.PAID
        return f"{len(rows)} marked paid"

    @action(permission="custom", destructive=True)
    async def refund(self, ctx: AdminContext, rows: list[Order]) -> None:
        for order in rows:
            order.status = OrderStatus.CANCELLED

    @action()
    async def move_to_tenant_2(self, ctx: AdminContext, rows: list[Order]) -> None:
        for order in rows:
            order.tenant_id = 2

    @action()
    async def duplicate(self, ctx: AdminContext, rows: list[Order]) -> None:
        """Creates rows; ``into`` (a test knob) picks their tenant."""
        for order in rows:
            ctx.session.add(
                Order(
                    tenant_id=DUPLICATE_INTO.get("tenant", order.tenant_id),
                    customer_id=order.customer_id,
                    status=order.status,
                    total=order.total,
                    created_at=order.created_at,
                )
            )


DUPLICATE_INTO: dict[str, int] = {}


class FailingAfterSave(ModelAdmin):
    name = "product"

    async def after_save(self, ctx: AdminContext, obj: Any, *, created: bool) -> None:
        if obj.name == "explode":
            raise RuntimeError("after_save failed")


class StaffAdmin(ModelAdmin):
    async def before_save(self, ctx: AdminContext, obj: Any, *, created: bool) -> None:
        obj.api_token = "rotated-secret"  # a hidden column changed by a hook


def build_site(engine: AsyncEngine) -> AdminSite:
    site = AdminSite(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        secret_key="writes-test-secret-" + "w" * 32,
        auth_backend=HeaderAuth(),
    )
    site.register(Customer, CustomerAdmin)
    site.register(Order, OrderAdmin)
    site.register(Tenant)
    site.register(Product, FailingAfterSave)
    site.register(Staff, StaffAdmin)
    return site


# ---- fixtures ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
async def schema(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(Staff.__table__.create, checkfirst=True)  # type: ignore[attr-defined]
    await migrate.upgrade(pg_engine)
    yield
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Staff.__table__.drop, checkfirst=True)  # type: ignore[attr-defined]
    await migrate.downgrade(pg_engine, "base")


@pytest.fixture
async def data(schema: None, pg_engine: AsyncEngine) -> dict[str, int]:
    """Fresh rows for every test: tenants 1 and 2, one customer and one order each."""
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                'TRUNCATE "order", customer, product, tenant, qe_staff, oneadmin_audit_log '
                "RESTART IDENTITY CASCADE"
            )
        )
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as s, s.begin():
        t1, t2 = Tenant(name="t1"), Tenant(name="t2")
        c1 = Customer(tenant=t1, email="c1@ex.com", full_name="One")
        c2 = Customer(tenant=t2, email="c2@ex.com", full_name="Two")
        s.add_all([t1, t2, c1, c2])
        await s.flush()
        o1 = Order(
            tenant_id=t1.id,
            customer=c1,
            status=OrderStatus.NEW,
            total=Decimal("10.00"),
            created_at=func.now(),
        )
        o2 = Order(
            tenant_id=t2.id,
            customer=c2,
            status=OrderStatus.PAID,
            total=Decimal("20.00"),
            created_at=func.now(),
        )
        staff = Staff(email="s@ex.com", password_hash="argon2$x", api_token="old-secret")
        s.add_all([o1, o2, staff])
        await s.flush()
        return {
            "t1": t1.id,
            "t2": t2.id,
            "c1": c1.id,
            "c2": c2.id,
            "o1": o1.id,
            "o2": o2.id,
            "staff": staff.id,
        }


@pytest.fixture(scope="module")
def site(pg_engine: AsyncEngine) -> AdminSite:
    return build_site(pg_engine)


@pytest.fixture
async def client(data: dict[str, int], site: AdminSite) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    site.mount(app, "/admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test/admin/api/v1",
        headers={"origin": "http://test"},
    ) as c:
        yield c


SUPER = {"x-test-user": "super"}
T1 = {"x-test-user": "tenant:1"}
VIEWER = {"x-test-user": "viewer:1"}


async def version(client: httpx.AsyncClient, path: str, headers: dict[str, str]) -> str:
    r = await client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    v: str = r.json()["version"]
    return v


async def audit_rows(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(t.audit_log).order_by(t.audit_log.c.id))
        return list(rows.mappings())


def error(r: httpx.Response) -> dict[str, Any]:
    body: dict[str, Any] = r.json()["error"]
    return body


# ---- create --------------------------------------------------------------------------------
async def test_create_returns_the_row_and_audits_it(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    r = await client.post(
        "/models/customer/rows",
        json={"tenant_id": data["t1"], "email": "NEW@ex.com", "full_name": "New"},
        headers=T1,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["values"]["email"] == "new@ex.com", "clean() may adjust values"
    assert body["values"]["tenant"]["label"] == "t1"
    assert body["version"]
    (entry,) = await audit_rows(pg_engine)
    assert (entry["action"], entry["model"], entry["object_pk"]) == (
        "create",
        "customer",
        body["pk"],
    )
    assert entry["actor_email"] == "tenant1@example.com"
    assert entry["changes"]["email"] == [None, "new@ex.com"]


async def test_create_reports_every_field_error_at_once(client: httpx.AsyncClient) -> None:
    r = await client.post("/models/customer/rows", json={"full_name": 5}, headers=T1)
    assert r.status_code == 400
    err = error(r)
    assert err["code"] == "validation_failed"
    assert err["fields"] == {
        "full_name": "must be text",
        "tenant_id": "is required",
        "email": "is required",
    }


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"id": 99}, "id", "is read-only"),  # generated primary key
        ({"is_vip": True}, "is_vip", "is not a writable field"),  # unknown
        ({"created_at": "2026-01-01T00:00:00+00:00"}, "created_at", "is read-only"),  # option
    ],
)
async def test_mass_assignment_is_refused_not_ignored(
    client: httpx.AsyncClient,
    data: dict[str, int],
    payload: dict[str, Any],
    field: str,
    message: str,
) -> None:
    base = {"tenant_id": data["t1"], "customer_id": data["c1"], "status": "new", "total": "1.00"}
    r = await client.post("/models/order/rows", json={**base, **payload}, headers=T1)
    assert r.status_code == 400, r.text
    assert error(r)["fields"] == {field: message}


async def test_hidden_columns_are_not_writable(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    pk = data["staff"]
    v = await version(client, f"/models/qe_staff/rows/{pk}", SUPER)
    r = await client.patch(
        f"/models/qe_staff/rows/{pk}", json={"password_hash": "x"}, headers={**SUPER, "if-match": v}
    )
    assert r.status_code == 400
    assert error(r)["fields"] == {"password_hash": "is not a writable field"}


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"total": 12.5}, "total", 'must be a decimal number, sent as a string (e.g. "12.50")'),
        ({"total": "1.234"}, "total", "must have at most 2 decimal places"),
        ({"total": "12345678901.00"}, "total", "number out of range for NUMERIC(12,2)"),
        ({"status": "bogus"}, "status", "must be one of new, paid, shipped, cancelled"),
        (
            {"shipped_at": "2026-01-01T00:00:00"},
            "shipped_at",
            "timezone offset required (e.g. 2026-01-31T12:00:00Z)",
        ),
        ({"customer_id": True}, "customer_id", "must be an integer"),
        ({"customer_id": 2**63}, "customer_id", "number out of range for this column"),
    ],
)
async def test_values_are_validated_per_column_type(
    client: httpx.AsyncClient,
    data: dict[str, int],
    payload: dict[str, Any],
    field: str,
    message: str,
) -> None:
    pk = data["o1"]
    v = await version(client, f"/models/order/rows/{pk}", T1)
    r = await client.patch(f"/models/order/rows/{pk}", json=payload, headers={**T1, "if-match": v})
    assert r.status_code == 400, r.text
    assert error(r)["fields"] == {field: message}


# ---- update --------------------------------------------------------------------------------
async def test_omitted_fields_are_unchanged_and_null_needs_a_nullable_column(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, T1)
    r = await client.patch(path, json={"notes": "hello"}, headers={**T1, "if-match": v})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["total"] == "10.00", "an omitted field keeps its value"

    v = r.json()["version"]
    r = await client.patch(path, json={"notes": None}, headers={**T1, "if-match": v})
    assert (r.status_code, r.json()["values"]["notes"]) == (200, None)

    r = await client.patch(
        path, json={"total": None}, headers={**T1, "if-match": r.json()["version"]}
    )
    assert r.status_code == 400
    assert error(r)["fields"] == {"total": "may not be empty"}


async def test_optimistic_concurrency(client: httpx.AsyncClient, data: dict[str, int]) -> None:
    path = f"/models/order/rows/{data['o1']}"
    r = await client.patch(path, json={"notes": "x"}, headers=T1)
    assert (r.status_code, error(r)["code"]) == (428, "precondition_required")

    stale = await version(client, path, T1)
    ok = await client.patch(path, json={"notes": "first"}, headers={**T1, "if-match": f'"{stale}"'})
    assert ok.status_code == 200, "a quoted ETag-style value is accepted"
    assert ok.json()["version"] != stale
    assert ok.headers["etag"] == f'"{ok.json()["version"]}"'

    lost = await client.patch(path, json={"notes": "second"}, headers={**T1, "if-match": stale})
    assert lost.status_code == 409
    err = error(lost)
    assert err["code"] == "conflict"
    assert err["current"]["values"]["notes"] == "first"
    assert err["current"]["version"] == ok.json()["version"]


async def test_an_update_without_changes_writes_no_audit(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, T1)
    r = await client.patch(path, json={"total": "10.00"}, headers={**T1, "if-match": v})
    assert r.status_code == 200
    assert r.json()["version"] == v
    assert await audit_rows(pg_engine) == []


# ---- the tenant boundary -------------------------------------------------------------------
async def test_foreign_rows_are_not_found_for_every_write(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    foreign = f"/models/order/rows/{data['o2']}"
    v = await version(client, foreign, SUPER)  # a valid version, obtained elsewhere
    headers = {**T1, "if-match": v}
    assert (await client.patch(foreign, json={"notes": "x"}, headers=headers)).status_code == 404
    assert (await client.delete(foreign, headers=headers)).status_code == 404
    r = await client.post(
        "/models/order/actions/mark_paid", json={"pks": [str(data["o2"])]}, headers=T1
    )
    assert r.status_code == 404
    assert (await client.get(f"{foreign}/history", headers=T1)).status_code == 404


async def test_moving_a_row_out_of_scope_is_refused_and_rolled_back(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    path = f"/models/customer/rows/{data['c1']}"
    v = await version(client, path, T1)
    r = await client.patch(path, json={"tenant_id": data["t2"]}, headers={**T1, "if-match": v})
    assert (r.status_code, error(r)["code"]) == (403, "out_of_scope")
    async with pg_engine.connect() as conn:
        tid = (
            await conn.execute(select(Customer.tenant_id).where(Customer.id == data["c1"]))
        ).scalar()
    assert tid == data["t1"]
    assert await audit_rows(pg_engine) == []


async def test_creating_in_another_tenant_is_refused(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    r = await client.post(
        "/models/customer/rows",
        json={"tenant_id": data["t2"], "email": "sneaky@ex.com", "full_name": "S"},
        headers=T1,
    )
    assert (r.status_code, error(r)["code"]) == (403, "out_of_scope")
    async with pg_engine.connect() as conn:
        n = (await conn.execute(select(func.count()).select_from(Customer))).scalar()
    assert n == 2
    assert await audit_rows(pg_engine) == []


async def test_foreign_keys_must_point_at_visible_rows(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, T1)
    r = await client.patch(path, json={"customer_id": data["c2"]}, headers={**T1, "if-match": v})
    assert r.status_code == 400
    assert error(r)["fields"] == {"customer_id": "no Customer with this key"}


# ---- permissions ---------------------------------------------------------------------------
async def test_view_only_users_cannot_write(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, VIEWER)
    attempts = [
        await client.post("/models/order/rows", json={}, headers=VIEWER),
        await client.patch(path, json={"notes": "x"}, headers={**VIEWER, "if-match": v}),
        await client.delete(path, headers={**VIEWER, "if-match": v}),
        await client.post(
            "/models/order/actions/mark_paid", json={"pks": [str(data["o1"])]}, headers=VIEWER
        ),
    ]
    assert [(r.status_code, error(r)["code"]) for r in attempts] == [(403, "forbidden")] * 4


async def test_models_without_view_permission_do_not_exist(client: httpx.AsyncClient) -> None:
    for r in (
        await client.get("/models/product/rows", headers=VIEWER),
        await client.post("/models/product/rows", json={}, headers=VIEWER),
    ):
        assert (r.status_code, error(r)["code"]) == (404, "unknown_model")


async def test_schema_is_per_user(client: httpx.AsyncClient) -> None:
    async def models(headers: dict[str, str]) -> dict[str, Any]:
        r = await client.get("/schema", headers=headers)
        return {m["slug"]: m for m in r.json()["models"]}

    viewer, tenant, root = await models(VIEWER), await models(T1), await models(SUPER)
    assert set(viewer) == {"customer", "order"}
    assert viewer["order"]["permissions"] == {
        "view": True,
        "add": False,
        "change": False,
        "delete": False,
    }
    assert viewer["order"]["actions"] == []
    assert tenant["order"]["permissions"] == {
        "view": True,
        "add": True,
        "change": True,
        "delete": True,
    }
    assert [a["name"] for a in tenant["order"]["actions"]] == [
        "delete_selected",
        "mark_paid",
        "move_to_tenant_2",
        "duplicate",
    ]
    assert "refund" in [a["name"] for a in root["order"]["actions"]], "custom permission"
    fields = {f["name"]: f for f in root["order"]["fields"]}
    assert (fields["id"]["writable"], fields["created_at"]["writable"]) == (False, False)
    assert (fields["total"]["writable"], fields["total"]["required"]) == (True, True)
    assert (fields["notes"]["writable"], fields["notes"]["required"]) == (True, False)


# ---- delete --------------------------------------------------------------------------------
async def test_delete(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    path = f"/models/order/rows/{data['o1']}"
    assert (await client.delete(path, headers=T1)).status_code == 428
    v = await version(client, path, T1)
    assert (await client.delete(path, headers={**T1, "if-match": v})).status_code == 204
    assert (await client.get(path, headers=T1)).status_code == 404
    (entry,) = await audit_rows(pg_engine)
    assert entry["action"] == "delete"
    assert entry["changes"]["total"] == ["10.00", None]


async def test_hooks_can_refuse_a_delete(client: httpx.AsyncClient, data: dict[str, int]) -> None:
    path = f"/models/order/rows/{data['o2']}"
    v = await version(client, path, SUPER)
    r = await client.delete(path, headers={**SUPER, "if-match": v})
    assert (r.status_code, error(r)["message"]) == (400, "Paid orders can't be deleted.")


async def test_constraint_violations_are_409(
    client: httpx.AsyncClient, data: dict[str, int]
) -> None:
    path = f"/models/customer/rows/{data['c1']}"  # still referenced by order o1
    v = await version(client, path, T1)
    r = await client.delete(path, headers={**T1, "if-match": v})
    assert (r.status_code, error(r)["code"]) == (409, "integrity_error")
    assert "fk_" not in r.text.lower() or "order" in r.text.lower()

    product = {"tenant_id": data["t1"], "sku": "SKU-1", "name": "P", "price": "1.00"}
    assert (await client.post("/models/product/rows", json=product, headers=T1)).status_code == 201
    dup = await client.post("/models/product/rows", json=product, headers=T1)
    assert (dup.status_code, error(dup)["code"], error(dup)["param"]) == (
        409,
        "integrity_error",
        "sku",
    )


# ---- actions -------------------------------------------------------------------------------
async def test_action_runs_and_audits_each_row(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    r = await client.post(
        "/models/order/actions/mark_paid", json={"pks": [str(data["o1"])]}, headers=T1
    )
    assert r.json() == {"count": 1, "message": "1 marked paid"}
    (entry,) = await audit_rows(pg_engine)
    assert entry["action"] == "action:mark_paid"
    assert entry["changes"] == {"status": ["new", "paid"]}


async def test_action_is_all_or_nothing_across_tenants(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    pks = [str(data["o1"]), str(data["o2"])]  # o2 belongs to tenant 2
    r = await client.post("/models/order/actions/mark_paid", json={"pks": pks}, headers=T1)
    assert r.status_code == 404
    async with pg_engine.connect() as conn:
        status = (await conn.execute(select(Order.status).where(Order.id == data["o1"]))).scalar()
    assert status is OrderStatus.NEW


async def test_action_that_moves_rows_out_of_scope_is_rolled_back(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    r = await client.post(
        "/models/order/actions/move_to_tenant_2", json={"pks": [str(data["o1"])]}, headers=T1
    )
    assert (r.status_code, error(r)["code"]) == (403, "out_of_scope")
    assert await audit_rows(pg_engine) == []


async def test_custom_action_permission(client: httpx.AsyncClient, data: dict[str, int]) -> None:
    body = {"pks": [str(data["o1"])]}
    assert (
        await client.post("/models/order/actions/refund", json=body, headers=T1)
    ).status_code == 403
    assert (
        await client.post("/models/order/actions/refund", json=body, headers=SUPER)
    ).status_code == 200


async def test_delete_selected(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    r = await client.post(
        "/models/order/actions/delete_selected", json={"pks": [str(data["o1"])]}, headers=T1
    )
    assert r.json() == {"count": 1, "message": "Deleted 1 order."}
    assert [e["action"] for e in await audit_rows(pg_engine)] == ["action:delete_selected"]


@pytest.mark.parametrize(
    ("path", "body", "status", "code"),
    [
        ("/models/order/actions/nope", {"pks": ["1"]}, 404, "unknown_action"),
        ("/models/order/actions/mark_paid", {"pks": []}, 400, "invalid_request"),
        ("/models/order/actions/mark_paid", {"pks": ["1"], "all": True}, 400, "invalid_request"),
        ("/models/order/actions/mark_paid", {"pks": ["x" * 2000]}, 404, "not_found"),
    ],
)
async def test_action_input_errors(
    client: httpx.AsyncClient, path: str, body: dict[str, Any], status: int, code: str
) -> None:
    r = await client.post(path, json=body, headers=T1)
    assert (r.status_code, error(r)["code"]) == (status, code)


# ---- audit ---------------------------------------------------------------------------------
async def test_a_failing_hook_rolls_back_the_change_and_its_audit(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    product = {"tenant_id": data["t1"], "sku": "BOOM", "name": "explode", "price": "1.00"}
    with pytest.raises(RuntimeError, match="after_save failed"):
        await client.post("/models/product/rows", json=product, headers=T1)
    async with pg_engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Product))).scalar() == 0
    assert await audit_rows(pg_engine) == []


async def test_a_failing_audit_rolls_back_the_change(
    client: httpx.AsyncClient,
    pg_engine: AsyncEngine,
    data: dict[str, int],
    site: AdminSite,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit storage unavailable")

    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, T1)
    monkeypatch.setattr(site.writes, "_audit", broken)
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        await client.patch(path, json={"notes": "unaudited"}, headers={**T1, "if-match": v})
    monkeypatch.undo()
    assert (await client.get(path, headers=T1)).json()["values"]["notes"] is None


async def test_hidden_columns_are_redacted_in_the_audit(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    path = f"/models/qe_staff/rows/{data['staff']}"
    v = await version(client, path, SUPER)
    r = await client.patch(path, json={"email": "new@ex.com"}, headers={**SUPER, "if-match": v})
    assert r.status_code == 200
    (entry,) = await audit_rows(pg_engine)
    assert entry["changes"] == {
        "email": ["s@ex.com", "new@ex.com"],
        "api_token": ["[hidden]", "[hidden]"],
    }
    assert "rotated-secret" not in str(entry)
    assert "old-secret" not in str(entry)


async def test_history(client: httpx.AsyncClient, data: dict[str, int]) -> None:
    path = f"/models/order/rows/{data['o1']}"
    v = await version(client, path, T1)
    r = await client.patch(path, json={"notes": "a"}, headers={**T1, "if-match": v})
    await client.patch(path, json={"notes": "b"}, headers={**T1, "if-match": r.json()["version"]})
    entries = (await client.get(f"{path}/history", headers=T1)).json()["entries"]
    assert [e["changes"]["notes"] for e in entries] == [["a", "b"], [None, "a"]]
    assert entries[0]["actor_email"] == "tenant1@example.com"


# ---- request guards ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("headers", "kwargs", "status"),
    [
        ({"origin": "https://evil.example"}, {"json": {}}, 403),
        ({}, {"data": {"email": "x"}}, 415),
        ({"content-length": str(3 * 1024 * 1024)}, {"content": b"{}"}, 413),
    ],
)
async def test_write_guards(
    client: httpx.AsyncClient, headers: dict[str, str], kwargs: dict[str, Any], status: int
) -> None:
    if "content" in kwargs:
        headers = {**headers, "content-type": "application/json"}
    r = await client.post("/models/customer/rows", headers={**T1, **headers}, **kwargs)
    assert r.status_code == status, r.text


async def test_non_object_bodies_are_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post("/models/customer/rows", json=[1, 2], headers=T1)
    assert (r.status_code, error(r)["code"]) == (400, "invalid_request")


async def test_writes_need_the_audit_table(
    client: httpx.AsyncClient, pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    await migrate.downgrade(pg_engine, "base")
    try:
        r = await client.post(
            "/models/customer/rows",
            json={"tenant_id": data["t1"], "email": "a@ex.com", "full_name": "A"},
            headers=T1,
        )
        assert (r.status_code, error(r)["code"]) == (503, "admin_not_migrated")
    finally:
        await migrate.upgrade(pg_engine)


async def test_rows_created_by_an_action_are_scope_checked_and_audited(
    client: httpx.AsyncClient,
    pg_engine: AsyncEngine,
    data: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"pks": [str(data["o1"])]}
    monkeypatch.setitem(DUPLICATE_INTO, "tenant", data["t2"])
    r = await client.post("/models/order/actions/duplicate", json=body, headers=T1)
    assert (r.status_code, error(r)["code"]) == (403, "out_of_scope")
    async with pg_engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Order))).scalar() == 2

    monkeypatch.delitem(DUPLICATE_INTO, "tenant")
    r = await client.post("/models/order/actions/duplicate", json=body, headers=T1)
    assert r.status_code == 200, r.text
    (entry,) = await audit_rows(pg_engine)
    assert entry["action"] == "action:duplicate"
    assert entry["changes"]["total"] == [None, "10.00"]


async def test_foreign_keys_without_a_relationship_are_scope_checked(
    pg_engine: AsyncEngine, data: dict[str, int]
) -> None:
    """``Order.tenant_id`` has a ForeignKey but no ``relationship()``."""

    class TenantAdmin(ModelAdmin):
        async def get_queryset(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
            tid = ctx.identity.extra.get("tenant_id")
            return stmt if tid is None else stmt.where(Tenant.id == tid)

    site = AdminSite(
        session_factory=async_sessionmaker(pg_engine, expire_on_commit=False),
        secret_key="writes-test-secret-" + "w" * 32,
        auth_backend=HeaderAuth(),
    )
    site.register(Order, OrderAdmin)
    site.register(Customer, CustomerAdmin)
    site.register(Tenant, TenantAdmin)
    app = FastAPI()
    site.mount(app, "/admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test/admin/api/v1",
        headers={"origin": "http://test"},
    ) as c:
        path = f"/models/order/rows/{data['o1']}"
        v = await version(c, path, T1)
        r = await c.patch(path, json={"tenant_id": data["t2"]}, headers={**T1, "if-match": v})
    assert r.status_code == 400
    assert error(r)["fields"] == {"tenant_id": "no Tenant with this key"}
