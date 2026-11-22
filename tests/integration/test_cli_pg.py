"""The ``oneadmin`` command, end to end: discovery, migrate, user and permission management,
check. Synchronous tests, because ``main()`` owns its event loop (as in a real terminal)."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from oneadmin.auth import migrate as migrations
from oneadmin.cli import Console, main

pytestmark = pytest.mark.pg

APP = ["--app", "tests.cli_site:site"]
PASSWORD = "a perfectly long password"


class FakeTerminal(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def console(stdin: str = "", *, tty: bool = False, answers: list[str] | None = None) -> Console:
    replies = iter(answers or [])
    return Console(
        stdin=FakeTerminal(stdin, tty=tty),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        getpass=lambda _prompt: next(replies),
        input=lambda _prompt: next(replies),
    )


def run(*argv: str, con: Console | None = None) -> tuple[int, str, str]:
    con = con or console()
    code = main([*APP, *argv], console=con)
    return code, con.stdout.getvalue(), con.stderr.getvalue()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def database(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ONEADMIN_TEST_CLI_URL", pg_url)
    run("migrate", "--downgrade", "base")
    yield
    run("migrate", "--downgrade", "base")


def test_migrate_is_idempotent() -> None:
    code, out, _ = run("migrate")
    assert code == 0
    assert f"none -> {migrations.head_revision()}" in out
    code, out, _ = run("migrate")
    assert (code, "up to date" in out) == (0, True)


def test_createsuperuser_non_interactive_and_duplicates() -> None:
    run("migrate")
    code, out, err = run(
        "createsuperuser",
        "--email",
        "Ops@Example.com",
        "--password-stdin",
        con=console(PASSWORD + "\n"),
    )
    assert (code, err) == (0, "")
    assert "ops@example.com created" in out
    code, _, err = run(
        "createsuperuser", "--email", "ops@example.com", "--password-stdin", con=console(PASSWORD)
    )
    assert code == 1
    assert "already exists" in err


def test_createsuperuser_interactive_retries_weak_and_mismatched() -> None:
    run("migrate")
    answers = ["not an email", "me@example.com", "short", PASSWORD, "different", PASSWORD, PASSWORD]
    code, out, err = run("createsuperuser", con=console(tty=True, answers=answers))
    assert code == 0, err
    assert "not a valid email" in err
    assert "at least 12 characters" in err
    assert "didn't match" in err
    assert "me@example.com created" in out


def test_createsuperuser_refuses_to_prompt_without_a_terminal() -> None:
    run("migrate")
    code, _, err = run("createsuperuser", con=console(tty=False))
    assert code == 1
    assert "--email is required" in err


def test_createsuperuser_before_migrate_explains_what_to_do() -> None:
    code, _, err = run(
        "createsuperuser", "--email", "a@b.co", "--password-stdin", con=console(PASSWORD)
    )
    assert code == 1
    assert "oneadmin migrate" in err


def test_changepassword() -> None:
    run("migrate")
    run("createsuperuser", "--email", "me@example.com", "--password-stdin", con=console(PASSWORD))
    code, out, _ = run(
        "changepassword", "me@example.com", "--password-stdin", con=console("another long password")
    )
    assert code == 0
    assert "signed out" in out
    code, _, err = run(
        "changepassword", "ghost@example.com", "--password-stdin", con=console(PASSWORD)
    )
    assert (code, "No admin user" in err) == (1, True)


def test_check_reports_migrations_superusers_and_index_advice() -> None:
    code, _, err = run("check")
    assert code == 1
    assert "Run `oneadmin migrate`" in err

    run("migrate")
    code, out, err = run("check")
    assert code == 0
    assert "no active superuser" in err
    assert "/qe_item" in out
    assert "qe_item.name: filterable, but not indexed" in out
    assert "qe_item.amount" in out  # sortable via list_display, no index
    assert "qe_item.grp" not in out  # led by ix_qe_item_grp_id


def test_discovery_errors_are_actionable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ONEADMIN_APP", raising=False)
    con = console()
    assert main(["check"], console=con) == 1
    assert "[tool.oneadmin]" in con.stderr.getvalue()  # type: ignore[attr-defined]

    (tmp_path / "pyproject.toml").write_text('[tool.oneadmin]\napp = "nope.module:site"\n')
    con = console()
    assert main(["check"], console=con) == 1
    assert "Could not import 'nope.module'" in con.stderr.getvalue()  # type: ignore[attr-defined]

    con = console()
    assert main(["--app", "tests.cli_site:engine", "check"], console=con) == 1
    assert "expected an AdminSite" in con.stderr.getvalue()  # type: ignore[attr-defined]


# ---- staff users and permissions (ADR-0019) ------------------------------------------------
def test_createuser_grant_revoke_perms() -> None:
    run("migrate")
    code, out, err = run(
        "createuser",
        "--email",
        "Staff@Example.com",
        "--password-stdin",
        "--grant",
        "qe_item.view",
        con=console(PASSWORD + "\n"),
    )
    assert code == 0, err
    assert "staff@example.com created. Permissions: qe_item.view." in out

    code, out, _ = run("grant", "staff@example.com", "qe_item.change", "qe_item.action.archive")
    assert (code, "Granted: qe_item.action.archive, qe_item.change." in out) == (0, True)
    assert "Nothing new" in run("grant", "staff@example.com", "qe_item.change")[1]

    assert run("perms", "staff@example.com")[1].split() == [
        "qe_item.action.archive",
        "qe_item.change",
        "qe_item.view",
    ]
    assert "Revoked 2" in run("revoke", "staff@example.com", "qe_item.view", "qe_item.change")[1]
    assert run("perms", "staff@example.com")[1].split() == ["qe_item.action.archive"]


@pytest.mark.parametrize(
    ("codename", "message"),
    [
        ("nope.view", "No model 'nope' is registered. Models: qe_item."),
        ("qe_item.edit", "is not a permission codename"),
        ("qe_item.action.publish", "'qe_item.action.publish' doesn't exist. Valid for 'qe_item':"),
    ],
)
def test_grant_refuses_unknown_codenames(codename: str, message: str) -> None:
    run("migrate")
    run("createuser", "--email", "s@example.com", "--password-stdin", con=console(PASSWORD + "\n"))
    code, _, err = run("grant", "s@example.com", codename)
    assert code == 1
    assert message in err


def test_superusers_have_every_permission() -> None:
    run("migrate")
    run(
        "createsuperuser",
        "--email",
        "root@example.com",
        "--password-stdin",
        con=console(PASSWORD + "\n"),
    )
    assert "is a superuser: every permission" in run("perms", "root@example.com")[1]


def test_check_lists_permission_codenames() -> None:
    run("migrate")
    out = run("check")[1]
    assert (
        "permissions: qe_item.view qe_item.add qe_item.change qe_item.delete "
        "qe_item.action.archive qe_item.*"
    ) in out


# ---- explain and schema (ADR-0020) ---------------------------------------------------------
def test_explain_model_lists_settings_and_origins() -> None:
    code, out, _ = run("explain", "qe_item")
    assert code == 0
    assert out.startswith("qe_item: tests.cli_site.ItemAdmin for tests.models.Item")
    assert "ordering      -grp" in out
    assert "ItemAdmin.ordering" in out
    assert "doubled" in out


def test_explain_field_says_why() -> None:
    code, out, _ = run("explain", "qe_item.doubled")
    assert code == 0
    assert re.search(r"writable +no +model: generated by the database", out)
    assert "model: generated by the database" in out
    code, out, _ = run("explain", "qe_item.name")
    assert "filterable" in out
    assert "ItemAdmin.list_filter" in out


def test_explain_unknown_targets() -> None:
    assert "No model 'nope' is registered. Models: qe_item." in run("explain", "nope")[2]
    assert "has no column attribute 'nope'" in run("explain", "qe_item.nope")[2]


def test_schema_and_diff(tmp_path: Path) -> None:
    code, out, _ = run("schema")
    assert code == 0
    snapshot = tmp_path / "admin.json"
    snapshot.write_text(out)
    assert run("schema", "--diff", str(snapshot))[:2] == (0, "No configuration changes.\n")

    data = json.loads(out)
    data["models"]["qe_item"]["list_display"] = ["id"]
    data["models"]["qe_item"]["fields"]["name"]["writable"] = False
    snapshot.write_text(json.dumps(data))
    code, out, _ = run("schema", "--diff", str(snapshot))
    assert code == 1
    assert "~ models.qe_item.fields.name.writable: false -> true" in out
    assert '~ models.qe_item.list_display: ["id"] -> ["id", "name", "grp", "amount"]' in out
