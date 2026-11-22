"""Built-in login, sessions, CSRF and rate limiting, over HTTP (threat model S1, S2, T1, I4).

The client uses ``https://test`` so the ``Secure`` session cookie is stored and sent, as in a
real browser.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from oneadmin import AdminSite
from oneadmin.auth import migrate
from oneadmin.auth import tables as t
from oneadmin.auth.service import AuthSettings, hash_token
from tests.models import Item

pytestmark = pytest.mark.pg

SECRET = "auth-test-secret-" + "z" * 32
EMAIL = "root@example.com"
PASSWORD = "correct horse battery staple"
ORIGIN = {"origin": "https://test"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture(scope="module")
async def migrated(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    await migrate.upgrade(pg_engine)
    yield
    await migrate.downgrade(pg_engine, "base")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def site(migrated: None, pg_engine: AsyncEngine, clock: Clock) -> AsyncIterator[AdminSite]:
    site = AdminSite(
        session_factory=async_sessionmaker(pg_engine, expire_on_commit=False),
        secret_key=SECRET,
        auth_settings=AuthSettings(max_failures_per_email=3, max_failures_per_ip=6),
        trusted_origins=["https://admin.partner.example"],
    )
    site.auth._clock = clock  # deterministic expiry tests
    site.register(Item)
    await site.auth.create_user(EMAIL, PASSWORD, is_superuser=True)
    yield site
    async with pg_engine.begin() as conn:
        for table in (t.session, t.login_attempt, t.user):
            await conn.execute(delete(table))


@pytest.fixture
def app(site: AdminSite) -> FastAPI:
    app = FastAPI()
    site.mount(app, "/admin")
    return app


def make_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test/admin/api/v1"
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as c:
        yield c


async def login(
    client: httpx.AsyncClient, email: str = EMAIL, password: str = PASSWORD, **headers: str
) -> httpx.Response:
    return await client.post(
        "/auth/login", json={"email": email, "password": password}, headers={**ORIGIN, **headers}
    )


# ---- login and session -------------------------------------------------------------------
async def test_login_sets_hardened_cookie_and_stores_only_a_hash(
    client: httpx.AsyncClient, pg_engine: AsyncEngine
) -> None:
    r = await login(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"] == {"id": body["user"]["id"], "email": EMAIL, "is_superuser": True}
    cookie = r.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/admin"):
        assert flag in cookie, cookie
    token = client.cookies["oneadmin_session"]
    async with pg_engine.connect() as conn:
        stored = (await conn.execute(select(t.session.c.token_hash))).scalars().all()
        password_hash = (await conn.execute(select(t.user.c.password_hash))).scalar_one()
    assert stored == [hash_token(token)], "only the SHA-256 of the token is stored"
    assert token not in stored
    assert password_hash.startswith("$argon2id$")


async def test_authenticated_requests_and_session_endpoint(client: httpx.AsyncClient) -> None:
    assert (await client.get("/schema")).status_code == 401
    csrf = (await login(client)).json()["csrf_token"]
    assert (await client.get("/schema")).status_code == 200
    session = (await client.get("/auth/session")).json()
    assert session["csrf_token"] == csrf
    assert session["user"]["email"] == EMAIL


async def test_email_is_case_and_space_insensitive(client: httpx.AsyncClient) -> None:
    assert (await login(client, email="  ROOT@Example.com ")).status_code == 200


async def test_failures_are_indistinguishable(client: httpx.AsyncClient, site: AdminSite) -> None:
    await site.auth.create_user("off@example.com", PASSWORD)
    async with site.session_factory() as s, s.begin():
        await s.execute(
            update(t.user).where(t.user.c.email == "off@example.com").values(is_active=False)
        )

    responses = [
        await login(client, password="wrong password here"),
        await login(client, email="nobody@example.com"),
        await login(client, email="off@example.com"),
        await login(client, email="not-an-email"),
    ]
    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1


async def test_malformed_email_attempts_count_toward_ip_limit(client: httpx.AsyncClient) -> None:
    for _ in range(6):
        assert (await login(client, email="not-an-email")).status_code == 401
    blocked = await login(client, email="not-an-email")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_unknown_user_costs_a_real_hash(client: httpx.AsyncClient) -> None:
    """Timing must not reveal whether an account exists (dummy-hash verification)."""

    async def timed(email: str) -> float:
        start = time.perf_counter()
        await login(client, email=email, password="wrong password here")
        return time.perf_counter() - start

    known = min([await timed(EMAIL) for _ in range(2)])
    unknown = min([await timed(f"ghost{i}@example.com") for i in range(2)])
    assert unknown > 0.5 * known, (known, unknown)


async def test_login_rotates_session_against_fixation(client: httpx.AsyncClient) -> None:
    planted = {"cookie": "oneadmin_session=attacker-chosen-token"}
    first = await login(client, **planted)
    assert first.cookies["oneadmin_session"] != "attacker-chosen-token"
    second = await login(client)
    assert second.cookies["oneadmin_session"] != first.cookies["oneadmin_session"]


async def replay(app: FastAPI, token: str) -> int:
    """Present ``token`` from a fresh client (as an attacker holding a stolen cookie would)."""
    async with make_client(app) as fresh:
        r = await fresh.get("/schema", headers={"cookie": f"oneadmin_session={token}"})
    return r.status_code


# ---- logout, password change, expiry ------------------------------------------------------
async def test_logout_requires_csrf_and_revokes(client: httpx.AsyncClient, app: FastAPI) -> None:
    response = await login(client)
    csrf, token = response.json()["csrf_token"], response.cookies["oneadmin_session"]
    assert await replay(app, token) == 200, "precondition: the token works before logout"
    no_csrf = await client.post("/auth/logout", json={}, headers=ORIGIN)
    assert (no_csrf.status_code, no_csrf.json()["error"]["code"]) == (403, "csrf_failed")
    wrong = await client.post("/auth/logout", json={}, headers={**ORIGIN, "x-csrf-token": "x" * 64})
    assert wrong.status_code == 403
    ok = await client.post("/auth/logout", json={}, headers={**ORIGIN, "x-csrf-token": csrf})
    assert ok.status_code == 204
    assert await replay(app, token) == 401, "a revoked token must not work"


async def test_password_change_revokes_all_sessions(
    client: httpx.AsyncClient, site: AdminSite
) -> None:
    await login(client)
    assert (await client.get("/schema")).status_code == 200
    await site.auth.set_password(EMAIL, "a brand new long password")
    assert (await client.get("/schema")).status_code == 401
    assert (await login(client)).status_code == 401
    assert (await login(client, password="a brand new long password")).status_code == 200


async def test_password_change_revokes_login_in_flight(
    site: AdminSite, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    original_verify = site.auth._hasher.verify

    async def paused_verify(stored: str | None, candidate: str) -> bool:
        entered.set()  # login has selected and locked the user row
        await release.wait()
        return await original_verify(stored, candidate)

    monkeypatch.setattr(site.auth._hasher, "verify", paused_verify)
    login_task = asyncio.create_task(site.auth.login(EMAIL, PASSWORD))
    await asyncio.wait_for(entered.wait(), timeout=5)
    change_task = asyncio.create_task(site.auth.set_password(EMAIL, "a brand new long password"))
    await asyncio.sleep(0.15)
    assert not change_task.done(), "password change must wait for the in-flight login"
    release.set()
    result = await asyncio.wait_for(login_task, timeout=5)
    await asyncio.wait_for(change_task, timeout=5)
    assert await site.auth.resolve(result.token) is None


async def test_idle_and_absolute_expiry(client: httpx.AsyncClient, clock: Clock) -> None:
    await login(client)
    clock.advance(hours=1, minutes=59)
    assert (await client.get("/schema")).status_code == 200, "activity extends the idle window"
    for _ in range(6):  # stay active, every 1h50m, up to 12h of absolute lifetime
        clock.advance(hours=1, minutes=50)
        status = (await client.get("/schema")).status_code
    assert status == 401, "absolute timeout ends even an active session"

    await login(client)
    clock.advance(hours=2, seconds=1)
    assert (await client.get("/schema")).status_code == 401, "idle timeout"


# ---- rate limiting -----------------------------------------------------------------------
async def test_email_rate_limit_blocks_even_the_right_password(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        assert (await login(client, password="wrong password here")).status_code == 401
    blocked = await login(client)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= 15 * 60


async def test_rate_limit_window_expires(client: httpx.AsyncClient, clock: Clock) -> None:
    for _ in range(3):
        await login(client, password="wrong password here")
    assert (await login(client)).status_code == 429
    clock.advance(minutes=15, seconds=1)
    assert (await login(client)).status_code == 200


async def test_success_resets_email_counter_but_not_ip_counter(client: httpx.AsyncClient) -> None:
    for _ in range(2):
        await login(client, password="wrong password here")
    assert (await login(client)).status_code == 200  # resets the email counter
    for _ in range(2):
        assert (await login(client, password="wrong password here")).status_code == 401
    # IP counter: 4 failures so far; 2 more against other emails reaches the IP limit of 6.
    for i in range(2):
        await login(client, email=f"x{i}@example.com", password="wrong password here")
    assert (await login(client)).status_code == 429, "IP limit survives a successful login"


# ---- CSRF / origin -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"origin": "https://evil.example"}, 403),
        ({"origin": "null"}, 403),
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"origin": "https://admin.partner.example"}, 200),  # trusted_origins
        ({"origin": "http://test"}, 200),  # TLS terminated at a proxy: scheme differs, host same
        ({"sec-fetch-site": "same-origin"}, 200),
    ],
)
async def test_login_origin_checks(
    client: httpx.AsyncClient, headers: dict[str, str], status: int
) -> None:
    r = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=headers
    )
    assert r.status_code == status, r.text


async def test_login_rejects_form_posts(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/login", data={"email": EMAIL, "password": PASSWORD}, headers=ORIGIN
    )
    assert (r.status_code, r.json()["error"]["code"]) == (415, "unsupported_media_type")


async def test_login_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/login",
        json={"email": EMAIL, "password": PASSWORD, "is_superuser": True},
        headers=ORIGIN,
    )
    assert r.status_code == 400


# ---- operational -------------------------------------------------------------------------
async def test_missing_tables_give_actionable_503(pg_engine: AsyncEngine) -> None:
    await migrate.downgrade(pg_engine, "base")
    try:
        site = AdminSite(session_factory=async_sessionmaker(pg_engine), secret_key=SECRET)
        site.register(Item)
        app = FastAPI()
        site.mount(app, "/admin")
        async with make_client(app) as c:
            r = await login(c)
            replayed = await c.get("/schema", headers={"cookie": "oneadmin_session=anything"})
        for response in (r, replayed):
            assert response.status_code == 503
            assert "oneadmin migrate" in response.json()["error"]["message"]
    finally:
        await migrate.upgrade(pg_engine)


def test_insecure_cookie_logs_a_warning(
    pg_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    AdminSite(session_factory=async_sessionmaker(pg_engine), secret_key=SECRET, cookie_secure=False)
    assert "plain HTTP" in caplog.text


# ---- writes and permissions with built-in users (ADR-0018, ADR-0019) -----------------------
async def test_writes_require_the_csrf_token(client: httpx.AsyncClient) -> None:
    csrf = (await login(client)).json()["csrf_token"]
    missing = await client.post("/models/qe_item/rows", json={}, headers=ORIGIN)
    assert (missing.status_code, missing.json()["error"]["code"]) == (403, "csrf_failed")
    wrong = await client.post(
        "/models/qe_item/rows", json={}, headers={**ORIGIN, "x-csrf-token": "0" * 64}
    )
    assert wrong.status_code == 403
    for method in ("PATCH", "DELETE"):
        r = await client.request(method, "/models/qe_item/rows/1", json={}, headers=ORIGIN)
        assert r.status_code == 403, method
    # With the token the request gets past the guards (and fails validation instead).
    ok = await client.post(
        "/models/qe_item/rows", json={}, headers={**ORIGIN, "x-csrf-token": csrf}
    )
    assert (ok.status_code, ok.json()["error"]["code"]) == (400, "validation_failed")


async def test_staff_users_see_only_granted_models(
    client: httpx.AsyncClient, site: AdminSite
) -> None:
    await site.auth.create_user("staff@example.com", PASSWORD)
    assert (await login(client, email="staff@example.com")).status_code == 200
    assert (await client.get("/schema")).json()["models"] == []
    assert (await client.get("/models/qe_item/rows")).status_code == 404

    assert await site.auth.grant("staff@example.com", ["qe_item.view"]) == ["qe_item.view"]
    (model,) = (await client.get("/schema")).json()["models"]
    assert model["permissions"] == {"view": True, "add": False, "change": False, "delete": False}
    assert model["actions"] == []

    assert await site.auth.revoke("staff@example.com", ["qe_item.view"]) == 1
    assert (await client.get("/schema")).json()["models"] == []
    assert await site.auth.permissions_of("staff@example.com") == (False, [])
