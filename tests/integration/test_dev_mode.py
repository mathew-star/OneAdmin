"""Development mode: local setup requires a token printed by the server."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oneadmin import AdminSite, ConfigurationError
from tests.e2e.server import Author, Base

PASSWORD = "a long enough dev password"


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dev.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def dev_site(engine: AsyncEngine) -> AdminSite:
    site = AdminSite(session_factory=async_sessionmaker(engine, expire_on_commit=False), dev=True)
    site.register_all([Author])
    return site


def client(site: AdminSite, client_ip: str = "127.0.0.1") -> httpx.AsyncClient:
    app = FastAPI()
    site.mount(app, "/admin")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(client_ip, 50000)),
        base_url="http://localhost/admin/api/v1",
        headers={"origin": "http://localhost"},
    )


async def test_zero_setup_flow(engine: AsyncEngine) -> None:
    """No configured secret, migration, or CLI account: first request migrates, setup creates
    the first admin and signs in, and setup closes afterwards."""
    site = dev_site(engine)
    async with client(site) as c:
        assert (await c.get("/auth/setup")).json() == {"needed": True}
        payload = {
            "email": "me@example.com",
            "password": PASSWORD,
            "setup_token": site.dev_setup_token,
        }
        denied = await c.post("/auth/setup", json={**payload, "setup_token": "wrong"})
        assert (denied.status_code, denied.json()["error"]["code"]) == (403, "invalid_setup_token")
        assert (await c.get("/auth/setup")).json() == {"needed": True}
        r = await c.post("/auth/setup", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["is_superuser"] is True
        token = r.cookies["oneadmin_session"]
        assert "Secure" not in r.headers["set-cookie"], "plain-HTTP cookies in dev"
        rows = await c.get("/models/authors/rows", headers={"cookie": f"oneadmin_session={token}"})
        assert rows.status_code == 200
        assert (await c.get("/auth/setup")).json() == {"needed": False}
        again = await c.post("/auth/setup", json={**payload, "email": "b@example.com"})
        assert (again.status_code, again.json()["error"]["code"]) == (409, "setup_done")


async def test_concurrent_setups_create_one_admin(engine: AsyncEngine) -> None:
    site = dev_site(engine)
    async with client(site) as c:
        results = await asyncio.gather(
            *(
                c.post(
                    "/auth/setup",
                    json={
                        "email": f"u{i}@example.com",
                        "password": PASSWORD,
                        "setup_token": site.dev_setup_token,
                    },
                )
                for i in range(5)
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]
    assert await site.auth.count_users() == 1


@pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.20", "203.0.113.9", "::ffff:10.0.0.1"])
async def test_only_loopback_clients_are_served(engine: AsyncEngine, ip: str) -> None:
    async with client(dev_site(engine), client_ip=ip) as c:
        for path in ("/auth/setup", "/schema"):
            r = await c.get(path)
            assert (r.status_code, r.json()["error"]["code"]) == (403, "dev_mode_local_only")
        page = await c.get("http://localhost/admin/")
        assert page.status_code == 403
        assert page.headers["x-frame-options"] == "DENY", "security headers still applied"


async def test_ipv6_loopback_is_served(engine: AsyncEngine) -> None:
    for ip in ("::1", "::ffff:127.0.0.1"):
        async with client(dev_site(engine), client_ip=ip) as c:
            assert (await c.get("/auth/setup")).status_code == 200


async def test_chunked_auth_body_is_limited(engine: AsyncEngine) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"{" + b"x" * (2 * 1024 * 1024)

    async with client(dev_site(engine)) as c:
        response = await c.post(
            "/auth/login",
            content=chunks(),
            headers={"content-type": "application/json"},
        )
    assert (response.status_code, response.json()["error"]["code"]) == (
        413,
        "payload_too_large",
    )
    assert response.headers["x-frame-options"] == "DENY"


async def test_setup_validates_input(engine: AsyncEngine) -> None:
    site = dev_site(engine)
    async with client(site) as c:
        weak = await c.post(
            "/auth/setup",
            json={
                "email": "me@example.com",
                "password": "short",
                "setup_token": site.dev_setup_token,
            },
        )
        assert (weak.status_code, weak.json()["error"]["param"]) == (400, "password")
        assert (await c.get("/auth/setup")).json() == {"needed": True}


async def test_setup_does_not_exist_outside_dev_mode(engine: AsyncEngine) -> None:
    site = AdminSite(
        session_factory=async_sessionmaker(engine), secret_key="s" * 32, cookie_secure=False
    )
    site.register_all([Author])
    from oneadmin.auth import migrate  # noqa: PLC0415

    await migrate.upgrade(engine)
    async with client(site) as c:
        assert (await c.get("/auth/setup")).json() == {"needed": False}
        r = await c.post(
            "/auth/setup",
            json={"email": "me@example.com", "password": PASSWORD, "setup_token": "unused"},
        )
        assert r.status_code == 404
        assert (await c.get("http://localhost/admin/api/v1/schema", headers={})).status_code == 401


def test_secret_key_is_required_outside_dev_mode(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("ONEADMIN_DEV", raising=False)
    with pytest.raises(ConfigurationError, match=r"secret_key=\.\.\.\) is required"):
        AdminSite(session_factory=async_sessionmaker(engine))
    monkeypatch.setenv("ONEADMIN_DEV", "1")
    with caplog.at_level(logging.WARNING, logger="oneadmin"):
        site = AdminSite(session_factory=async_sessionmaker(engine))
    assert site.dev
    assert "DEVELOPMENT MODE" in caplog.text
