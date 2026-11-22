"""The wire-size limit must not depend on a truthful Content-Length header."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from oneadmin.api.body_limit import BodyLimitMiddleware


async def echo_size(request: Request) -> JSONResponse:
    return JSONResponse({"bytes": len(await request.body())})


def client(limit: int = 8) -> httpx.AsyncClient:
    app = Starlette(routes=[Route("/write", echo_size, methods=["POST"])])
    app.add_middleware(BodyLimitMiddleware, max_bytes=limit)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_chunked_body_is_limited_by_actual_bytes() -> None:
    async with client() as c:
        response = await c.post("/write", content=chunks(b"12345", b"6789"))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_body_at_limit_is_replayed_to_route() -> None:
    async with client() as c:
        response = await c.post("/write", content=chunks(b"123", b"45678"))
    assert response.status_code == 200
    assert response.json() == {"bytes": 8}


async def test_declared_size_is_rejected_before_reading_body() -> None:
    async with client() as c:
        response = await c.post("/write", content=b"ok", headers={"content-length": "9"})
    assert response.status_code == 413
