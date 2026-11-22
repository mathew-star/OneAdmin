"""``oneadmin init``: generated admin.py compiles, is formatted, and matches register_all."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest

from oneadmin.cli import Console, main

PROJECT_MODELS = """
from datetime import datetime
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "init_author"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200))


class Book(Base):
    __tablename__ = "init_book"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    isbn_code: Mapped[str] = mapped_column(String(20))
    in_print: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    author_id: Mapped[int] = mapped_column(ForeignKey("init_author.id"))
    author: Mapped[Author] = relationship()
"""

PROJECT_DB = """
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

engine = create_async_engine("sqlite+aiosqlite://")
async_session_maker = async_sessionmaker(engine)
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pkg = tmp_path / "src" / "shopapp"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "models.py").write_text(PROJECT_MODELS)
    (pkg / "database.py").write_text(PROJECT_DB)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in [m for m in sys.modules if m.startswith("shopapp")]:
        monkeypatch.delitem(sys.modules, name)
    return tmp_path


def run(*argv: str) -> tuple[int, str, str]:
    con = Console(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
    code = main(list(argv), console=con)
    return code, con.stdout.getvalue(), con.stderr.getvalue()  # type: ignore[attr-defined]


def test_init_writes_a_working_formatted_admin(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, err = run("init", "--models", "shopapp.models", "--title", "Shop")
    assert code == 0, err
    target = project / "src" / "shopapp" / "admin.py"
    assert (
        "Wrote src/shopapp/admin.py: 2 model(s), session factory shopapp.database:async_session_maker."
        in out
    )
    assert '[tool.oneadmin] app = "shopapp.admin:admin"' in out
    source = target.read_text()
    assert "class BookAdmin(ModelAdmin[Book]):" in source
    assert 'search_fields = (Book.title, "^isbn_code")' in source
    assert "ordering = (Book.created_at.desc(),)" in source
    assert "cv.field_type(EmailField()" in source

    ruff = subprocess.run(  # noqa: S603 - our own tool on a file we wrote
        [sys.executable, "-m", "ruff", "format", "--check", "--line-length", "100", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ruff.returncode == 0, ruff.stdout + ruff.stderr

    monkeypatch.setenv("ONEADMIN_DEV", "1")
    spec = importlib.util.spec_from_file_location("shopapp.admin", target)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.admin.build_app()
    book = module.admin.admin_by_slug("init_book")
    assert book.compiled.list_display == (
        "id",
        "title",
        "author",
        "isbn_code",
        "in_print",
        "created_at",
    )
    assert book.compiled.filter_fields == ("in_print", "created_at")


def test_init_refuses_to_overwrite(project: Path) -> None:
    assert run("init", "--models", "shopapp.models")[0] == 0
    code, _, err = run("init", "--models", "shopapp.models")
    assert code == 1
    assert "already exists. Pass --force" in err
    assert run("init", "--models", "shopapp.models", "--force")[0] == 0


def test_init_explains_missing_pieces(project: Path) -> None:
    (project / "src" / "shopapp" / "database.py").write_text("")
    code, _, err = run("init", "--models", "shopapp.models")
    assert code == 1
    assert "No async_sessionmaker found" in err
    code, _, err = run("init", "--models", "shopapp.database", "--session", "x:y")
    assert "No mapped models found in shopapp.database" in err
    assert run("init", "--models", "nope.models")[2].startswith(
        "error: Could not import 'nope.models'"
    )


def test_init_with_a_declarative_base(project: Path) -> None:
    code, out, _ = run("init", "--models", "shopapp.models:Base", "--stdout")
    assert code == 0
    assert "from shopapp.models import Author, Book" in out
