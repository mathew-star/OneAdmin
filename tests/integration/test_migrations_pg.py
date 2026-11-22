"""OneAdmin's packaged migrations, and coexistence with the host app's own Alembic setup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column as C
from sqlalchemy import Connection, Integer, MetaData, String, inspect
from sqlalchemy import Table as T
from sqlalchemy.ext.asyncio import AsyncEngine

from oneadmin.alembic import include_object
from oneadmin.auth import migrate
from oneadmin.auth.tables import VERSION_TABLE, metadata

pytestmark = pytest.mark.pg


@pytest.fixture
async def clean(pg_engine: AsyncEngine) -> AsyncIterator[None]:
    await migrate.downgrade(pg_engine, "base")
    yield
    await migrate.downgrade(pg_engine, "base")


async def _tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


@pytest.mark.usefixtures("clean")
async def test_upgrade_matches_table_definitions_and_downgrade_removes_everything(
    pg_engine: AsyncEngine,
) -> None:
    assert await migrate.current_revision(pg_engine) is None
    await migrate.upgrade(pg_engine)
    assert await migrate.current_revision(pg_engine) == migrate.head_revision()

    def diff(conn: Connection) -> list[Any]:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "version_table": VERSION_TABLE,  # as in oneadmin's env.py
                "include_object": lambda o, n, t, r, c: t != "table" or n.startswith("oneadmin_"),
            },
        )
        diffs: list[Any] = compare_metadata(ctx, metadata)
        return diffs

    async with pg_engine.connect() as conn:
        assert await conn.run_sync(diff) == [], "migrations and auth/tables.py have drifted"

    await migrate.upgrade(pg_engine)  # idempotent
    await migrate.downgrade(pg_engine, "base")
    leftovers = {t for t in await _tables(pg_engine) if t.startswith("oneadmin_")}
    assert leftovers <= {VERSION_TABLE}


@pytest.mark.usefixtures("clean")
async def test_host_app_autogenerate_leaves_oneadmin_tables_alone(pg_engine: AsyncEngine) -> None:
    """Without the helper, the app's autogenerate would DROP our tables (the hazard is real)."""
    await migrate.upgrade(pg_engine)
    app_metadata = MetaData()
    T("host_thing", app_metadata, C("id", Integer, primary_key=True), C("name", String(10)))

    def removals(conn: Connection, *, helper: bool) -> set[str]:
        opts: dict[str, Any] = {"include_object": include_object} if helper else {}
        ctx = MigrationContext.configure(conn, opts=opts)
        return {d[1].name for d in compare_metadata(ctx, app_metadata) if d[0] == "remove_table"}

    async with pg_engine.connect() as conn:
        without = await conn.run_sync(lambda c: removals(c, helper=False))
        with_helper = await conn.run_sync(lambda c: removals(c, helper=True))
    assert {"oneadmin_user", "oneadmin_session", "oneadmin_login_attempt"} <= without
    assert not {t for t in with_helper if t.startswith("oneadmin_")}
