"""Operation middleware (ADR-0020): wraps every operation, can't bypass the core."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oneadmin import AdminIdentity, AdminSite, ConfigurationError
from oneadmin.auth import migrate
from oneadmin.core.errors import PermissionDenied
from oneadmin.core.operations import CallNext, Operation
from tests.e2e.server import Author, Base

ROOT = AdminIdentity(id="1", email="root@ex.com", is_superuser=True)
VIEWER = AdminIdentity(id="2", email="v@ex.com", permissions=frozenset({"authors.view"}))


class HeaderAuth:
    async def authenticate(self, request: Any) -> AdminIdentity | None:
        return {"root": ROOT, "viewer": VIEWER}.get(request.headers.get("x-user", ""))


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mw.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate.upgrade(engine)
    yield engine
    await engine.dispose()


def make_site(engine: AsyncEngine) -> AdminSite:
    site = AdminSite(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        secret_key="m" * 32,
        auth_backend=HeaderAuth(),
    )
    site.register(Author)
    return site


async def client_for(site: AdminSite) -> httpx.AsyncClient:
    app = FastAPI()
    site.mount(app, "/admin")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t/admin/api/v1",
        headers={"origin": "http://t", "x-user": "root"},
    )


async def test_middleware_wraps_every_operation_in_registration_order(engine: AsyncEngine) -> None:
    site = make_site(engine)
    log: list[str] = []

    @site.middleware
    async def outer(op: Operation, call_next: CallNext) -> Any:
        log.append(f"outer>{op.kind}")
        result = await call_next()
        log.append(f"outer<{op.kind}")
        return result

    @site.middleware
    async def inner(op: Operation, call_next: CallNext) -> Any:
        log.append(f"inner>{op.kind}:{op.slug}")
        return await call_next()

    async with await client_for(site) as c:
        created = await c.post("/models/authors/rows", json={"name": "A", "email": "a@x.io"})
        pk = created.json()["pk"]
        await c.get("/models/authors/rows")
        await c.get(f"/models/authors/rows/{pk}")
    assert log == [
        "outer>create", "inner>create:authors", "outer<create",
        "outer>list", "inner>list:authors", "outer<list",
        "outer>get", "inner>get:authors", "outer<get",
    ]  # fmt: skip


async def test_writes_are_committed_when_call_next_returns(engine: AsyncEngine) -> None:
    site = make_site(engine)
    seen: list[int] = []

    @site.middleware
    async def count_after(op: Operation, call_next: CallNext) -> Any:
        result = await call_next()
        if op.kind == "create":  # a *different* connection already sees the row
            async with engine.connect() as conn:
                seen.append(
                    (await conn.execute(select(func.count()).select_from(Author))).scalar_one()
                )
        return result

    async with await client_for(site) as c:
        r = await c.post("/models/authors/rows", json={"name": "B", "email": "b@x.io"})
    assert r.status_code == 201
    assert seen == [1]


async def test_middleware_can_refuse_an_operation(engine: AsyncEngine) -> None:
    site = make_site(engine)

    @site.middleware
    async def read_only_mode(op: Operation, call_next: CallNext) -> Any:
        if op.is_write:
            raise PermissionDenied("The admin is read-only during maintenance.")
        return await call_next()

    async with await client_for(site) as c:
        r = await c.post("/models/authors/rows", json={"name": "C", "email": "c@x.io"})
        assert (r.status_code, r.json()["error"]["message"]) == (
            403,
            "The admin is read-only during maintenance.",
        )
        assert (await c.get("/models/authors/rows")).status_code == 200


async def test_the_core_still_runs_inside_the_chain(engine: AsyncEngine) -> None:
    """Permission checks and validation happen inside call_next: middleware sees the error."""
    site = make_site(engine)
    errors: list[str] = []

    @site.middleware
    async def watch(op: Operation, call_next: CallNext) -> Any:
        try:
            return await call_next()
        except Exception as exc:
            errors.append(type(exc).__name__)
            raise

    async with await client_for(site) as c:
        bad = await c.post("/models/authors/rows", json={"nickname": "x"})
    assert bad.status_code == 400
    assert errors == ["ValidationError"]


async def test_call_next_twice_is_an_error(engine: AsyncEngine) -> None:
    site = make_site(engine)

    @site.middleware
    async def twice(op: Operation, call_next: CallNext) -> Any:
        await call_next()
        return await call_next()

    async with await client_for(site) as c:
        with pytest.raises(RuntimeError, match="called twice"):
            await c.get("/models/authors/rows")


def test_middleware_must_be_registered_before_mount(engine: AsyncEngine) -> None:
    site = make_site(engine)
    site.build_app()
    with pytest.raises(ConfigurationError, match="before mount"):
        site.middleware(lambda op, call_next: call_next())
