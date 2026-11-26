"""Development mode (``AdminSite(dev=True)``): a peer loopback guard and migrations.

Pure ASGI, so it runs before routing and for static files too. A local reverse proxy can
make a remote request appear loopback; first-run setup also requires a server-side token.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Awaitable, Callable

from starlette.types import ASGIApp, Receive, Scope, Send

_FORBIDDEN = json.dumps(
    {
        "error": {
            "code": "dev_mode_local_only",
            "message": "This admin runs in development mode and only serves local connections.",
            "param": None,
        }
    }
).encode()


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (getattr(ip, "ipv4_mapped", None) or ip).is_loopback
    except ValueError:
        return False


class DevModeMiddleware:
    """Refuse non-loopback clients, and run ``prepare`` once before the first request."""

    def __init__(self, app: ASGIApp, prepare: Callable[[], Awaitable[None]]) -> None:
        self.app = app
        self._prepare = prepare
        self._ready = False
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        if not is_loopback(client[0] if client else None):
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": _FORBIDDEN})
            return
        if not self._ready:
            async with self._lock:
                if not self._ready:
                    await self._prepare()
                    self._ready = True
        await self.app(scope, receive, send)
