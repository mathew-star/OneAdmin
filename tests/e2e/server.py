"""A self-contained admin app for the browser tests (``frontend/e2e``).

SQLite in a temporary file, a small seeded blog schema, the built-in login with one
superuser, mounted at ``/backoffice`` (not ``/admin``) to prove the UI works under any prefix.

Run it directly to try the UI without a database server::

    uv run python tests/e2e/server.py --port 8765
    # open http://localhost:8765/backoffice/  (e2e@example.com / e2e password 1234)
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from oneadmin import AdminContext, AdminSite, ModelAdmin, action
from oneadmin import conventions as cv
from oneadmin.auth import migrate
from oneadmin.fields import EmailField

EMAIL = "e2e@example.com"
PASSWORD = "e2e password 1234"
PREFIX = "/backoffice"
N_POSTS = 120


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    published: Mapped[bool] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"), index=True)
    author: Mapped[Author] = relationship()


def build_site(engine: AsyncEngine) -> AdminSite:
    site = AdminSite(
        title="E2E Blog",
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        secret_key="e2e-secret-key-" + "x" * 32,
        conventions=[cv.field_type(EmailField(), "email")],
    )

    @site.register(Author)
    class AuthorAdmin(ModelAdmin):
        list_display = ("id", "name", "email")
        search_fields = ("name", "email")
        ordering = ("name",)

    @site.register(Post)
    class PostAdmin(ModelAdmin):
        list_display = ("id", "title", "author", "published", "created_at")
        list_filter = ("published", "created_at")
        search_fields = ("title",)
        ordering = ("-created_at",)
        list_per_page = 25

        @action(label="Publish", confirm="Publish the selected posts?")
        async def publish(self, ctx: AdminContext, rows: list[Post]) -> str:
            for post in rows:
                post.published = True
            return f"Published {len(rows)} post(s)."

    return site


async def prepare(engine: AsyncEngine, site: AdminSite) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate.upgrade(engine)
    start = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    async with site.session_factory() as session, session.begin():
        authors = [Author(name=f"Author {i:02d}", email=f"author{i}@example.com") for i in range(5)]
        session.add_all(authors)
        session.add_all(
            Post(
                title=f"Post number {i:03d}",
                published=i % 3 != 0,
                created_at=start + timedelta(hours=i),
                author=authors[i % len(authors)],
            )
            for i in range(N_POSTS)
        )
    await site.auth.create_user(EMAIL, PASSWORD, is_superuser=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="oneadmin-e2e-"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{workdir / 'e2e.db'}")
    site = build_site(engine)
    asyncio.run(prepare(engine, site))

    app = FastAPI()
    site.mount(app, PREFIX)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
