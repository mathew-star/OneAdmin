"""``oneadmin demo``: seed the demo shop and serve it (needs ``oneadmin[demo]``)."""

from __future__ import annotations

import argparse
import asyncio
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oneadmin.auth import migrate
from oneadmin.core.errors import OneAdminError

if TYPE_CHECKING:
    from oneadmin.cli import Console

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "oneadmin demo password"  # noqa: S105 - printed for the local demo on purpose


def demo(args: argparse.Namespace, console: Console) -> int:
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        raise OneAdminError(
            "The demo needs extra packages: pip install 'oneadmin[demo]' (or uv add 'oneadmin[demo]')."
        ) from None
    url = args.database or _default_url(args.rows, reset=args.reset)
    app = asyncio.run(prepare(url, args.rows, console))
    address = f"http://127.0.0.1:{args.port}/admin/"
    console.say(f"\nOneAdmin demo: {address}")
    console.say(f"  email:    {DEMO_EMAIL}")
    console.say(f"  password: {DEMO_PASSWORD}")
    console.say("  (development mode: only this computer can connect; Ctrl+C to stop)\n")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(address,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


async def prepare(url: str, rows: int, console: Console) -> Any:
    """Create, seed (once) and migrate the demo database; return the ASGI app to serve."""
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.responses import RedirectResponse  # noqa: PLC0415

    from oneadmin.demo.models import Base, Order  # noqa: PLC0415
    from oneadmin.demo.seed import seed  # noqa: PLC0415
    from oneadmin.demo.site import build_site  # noqa: PLC0415

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        existing = (await conn.execute(select(func.count()).select_from(Order))).scalar_one()
    if existing == 0:
        console.say(f"Seeding {rows:,} orders (once; a million take about 15 seconds)...")
        async with engine.begin() as conn:
            await seed(conn, rows)
    else:
        console.say(f"Using the existing demo database ({existing:,} orders).")
    await migrate.upgrade(engine)
    site = build_site(async_sessionmaker(engine, expire_on_commit=False))
    if await site.auth.count_users() == 0:
        await site.auth.create_user(DEMO_EMAIL, DEMO_PASSWORD, is_superuser=True)
    await _analyze(engine)

    app = FastAPI()
    site.mount(app, "/admin")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/admin/")

    return app


async def _analyze(engine: AsyncEngine) -> None:
    """Refresh planner statistics after seeding (cheap; keeps estimated counts honest)."""
    from sqlalchemy import text  # noqa: PLC0415, TID251 - a fixed maintenance statement

    async with engine.begin() as conn:
        await conn.execute(text("ANALYZE"))


def _default_url(rows: int, *, reset: bool) -> str:
    folder = Path.home() / ".cache" / "oneadmin"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"demo-{rows}.sqlite3"
    if reset and path.exists():
        path.unlink()
    return f"sqlite+aiosqlite:///{path}"
