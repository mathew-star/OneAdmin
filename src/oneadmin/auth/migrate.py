"""Apply OneAdmin's packaged migrations to the application's database.

They use a separate Alembic version table (``oneadmin_alembic_version``), so they never
interfere with the host app's own migration history (ADR-0012).
"""

from __future__ import annotations

from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from oneadmin.auth.tables import VERSION_TABLE

SCRIPT_LOCATION = "oneadmin.auth:migrations"


def _config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    if connection is not None:
        config.attributes["connection"] = connection
    return config


async def upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    """Bring OneAdmin's tables up to ``revision``. Safe to run repeatedly."""
    await _run(engine, lambda conn: command.upgrade(_config(conn), revision))


async def downgrade(engine: AsyncEngine, revision: str) -> None:
    """Revert to ``revision``; ``"base"`` drops every OneAdmin table."""
    await _run(engine, lambda conn: command.downgrade(_config(conn), revision))


async def current_revision(engine: AsyncEngine) -> str | None:
    """The applied revision, or ``None`` if OneAdmin's tables were never created."""

    def read(conn: Connection) -> str | None:
        ctx = MigrationContext.configure(conn, opts={"version_table": VERSION_TABLE})
        return ctx.get_current_revision()

    async with engine.connect() as conn:
        return await conn.run_sync(read)


def head_revision() -> str:
    head = ScriptDirectory.from_config(_config()).get_current_head()
    if head is None:  # pragma: no cover - the package always ships migrations
        raise RuntimeError("OneAdmin ships no migrations; the installation is broken")
    return head


async def _run(engine: AsyncEngine, fn: Any) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(fn)
