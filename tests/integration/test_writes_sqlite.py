"""The write path on SQLite (supported for development): create, update, delete, actions,
history and constraint errors, called through the service layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from oneadmin import AdminContext, AdminIdentity, AdminSite
from oneadmin.auth import migrate
from oneadmin.core.errors import Conflict, IntegrityConflict
from tests.e2e.server import Base, build_site

ROOT = AdminIdentity(id="1", email="root@example.com", is_superuser=True)


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'w.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate.upgrade(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def site(engine: AsyncEngine) -> AdminSite:
    site = build_site(engine)
    site.build_app()
    return site


async def call(site: AdminSite, method: str, *args: Any) -> Any:
    async with ctx(site) as c:
        return await getattr(site.writes, method)(c, *args)


@asynccontextmanager
async def ctx(site: AdminSite) -> AsyncIterator[AdminContext]:
    """One request's context, with its own session (as the API creates per request)."""
    async with site.session_factory() as session:
        yield AdminContext(identity=ROOT, session=session)


async def test_write_lifecycle(site: AdminSite) -> None:
    authors = site.admin_by_slug("authors")
    posts = site.admin_by_slug("posts")
    assert authors is not None
    assert posts is not None

    author = await call(site, "create", authors, {"name": "Ada", "email": "a@ex.com"})
    post = await call(
        site,
        "create",
        posts,
        {
            "title": "Hello",
            "published": False,
            "created_at": "2026-01-01T10:00:00",
            "author_id": int(author.pk),
        },
    )
    assert post.values["author"] == {"pk": author.pk, "label": "Ada"}

    assert post.version is not None
    updated = await call(site, "update", posts, post.pk, {"published": True}, post.version)
    assert updated.values["published"] is True
    with pytest.raises(Conflict):
        await call(site, "update", posts, post.pk, {"title": "x"}, post.version)

    result = await call(site, "run_action", posts, "delete_selected", [post.pk])
    assert result.count == 1
    history = await call(site, "history", authors, author.pk)
    assert history is not None
    assert [e.action for e in history] == ["create"]


async def test_sqlite_constraint_errors_name_the_field(site: AdminSite) -> None:
    authors = site.admin_by_slug("authors")
    assert authors is not None
    await call(site, "create", authors, {"name": "A", "email": "dup@ex.com"})
    with pytest.raises(IntegrityConflict) as info:
        await call(site, "create", authors, {"name": "B", "email": "dup@ex.com"})
    assert info.value.param == "email"
