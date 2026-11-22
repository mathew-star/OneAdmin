"""The ``oneadmin`` command (Django-style management commands, ADR-0016).

    oneadmin migrate                       create/upgrade OneAdmin's tables
    oneadmin createsuperuser               create an admin user (prompts)
    oneadmin createuser                    create a staff user (no permissions until granted)
    oneadmin changepassword EMAIL          set a password, revoking that user's sessions
    oneadmin grant EMAIL CODENAME...       grant permissions, e.g. orders.view orders.change
    oneadmin revoke EMAIL CODENAME...      revoke permissions
    oneadmin perms EMAIL                   show a user's permissions
    oneadmin check                         validate registrations, list permission codenames,
                                           advise on indexes
    oneadmin init --models app.models      write a starting admin.py for your models
    oneadmin demo                          a seeded 1M-order shop in your browser
    oneadmin convert sqladmin FILE         rewrite sqladmin ModelView classes as ModelAdmin
    oneadmin explain MODEL[.FIELD]         the resolved configuration and why
    oneadmin schema [--diff FILE]          the configuration as JSON, or what changed

Every command finds the app's ``AdminSite`` via ``--app``, ``ONEADMIN_APP`` or
``[tool.oneadmin]`` in ``pyproject.toml`` (see ``discovery``), and uses the site's own
database engine.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import rich_click as click

from oneadmin.__about__ import __version__
from oneadmin.core.errors import OneAdminError

__all__ = ["main"]


@dataclass
class Console:
    """The command's I/O, injectable so commands are testable without a terminal."""

    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    getpass: Callable[[str], str] = getpass.getpass
    input: Callable[[str], str] = input

    def say(self, message: str) -> None:
        print(message, file=self.stdout)

    def warn(self, message: str) -> None:
        print(message, file=self.stderr)

    @property
    def interactive(self) -> bool:
        return self.stdin.isatty()


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, no_args_is_help=True)
@click.version_option(__version__, prog_name="oneadmin")
@click.option("--app", help="AdminSite import path, for example app.admin:admin.")
def cli(app: str | None) -> None:
    """Manage a OneAdmin site. Run COMMAND --help for command options."""


def _dispatch(ctx: click.Context, name: str, **values: Any) -> int:
    """Keep argument parsing separate from the existing, testable command handlers."""
    from argparse import Namespace  # noqa: PLC0415

    from oneadmin.cli import commands  # noqa: PLC0415
    from oneadmin.cli.discovery import load_site, resolve_reference  # noqa: PLC0415

    console: Console = ctx.obj if isinstance(ctx.obj, Console) else Console()
    args = Namespace(command=name, app=ctx.find_root().params.get("app"), **values)
    if name in SITELESS:
        return SITELESS[name](args, console)
    handlers = {
        "migrate": commands.migrate,
        "createsuperuser": commands.createsuperuser,
        "createuser": commands.createuser,
        "changepassword": commands.changepassword,
        "grant": commands.grant,
        "revoke": commands.revoke,
        "perms": commands.perms,
        "check": commands.check,
        "explain": commands.explain,
        "schema": commands.schema,
    }
    cwd = Path.cwd()
    site = load_site(resolve_reference(args.app, cwd), cwd)
    return asyncio.run(commands.run(handlers[name], site, args, console))


@cli.command(help="Create or upgrade OneAdmin's database tables.")
@click.option("--revision", default="head", show_default=True, help="Target revision.")
@click.option("--downgrade", metavar="REVISION", help="Revert instead; base drops the tables.")
@click.pass_context
def migrate(ctx: click.Context, revision: str, downgrade: str | None) -> int:
    return _dispatch(ctx, "migrate", revision=revision, downgrade=downgrade)


@cli.command(help="Create an administrator with full access.")
@click.option("--email", help="Administrator email; prompted if omitted.")
@click.option("--password-stdin", is_flag=True, help="Read password from standard input.")
@click.pass_context
def createsuperuser(ctx: click.Context, email: str | None, password_stdin: bool) -> int:
    return _dispatch(ctx, "createsuperuser", email=email, password_stdin=password_stdin)


@cli.command(help="Create a staff account; grant access separately or with --grant.")
@click.option("--email", help="Staff email; prompted if omitted.")
@click.option("--password-stdin", is_flag=True, help="Read password from standard input.")
@click.option(
    "--grant",
    "grants",
    multiple=True,
    metavar="CODENAME",
    help="Grant a permission; repeat for more.",
)
@click.pass_context
def createuser(
    ctx: click.Context, email: str | None, password_stdin: bool, grants: tuple[str, ...]
) -> int:
    return _dispatch(
        ctx, "createuser", email=email, password_stdin=password_stdin, grant=list(grants)
    )


@cli.command(help="Grant one or more permission codenames to a user.")
@click.argument("email")
@click.argument("codenames", nargs=-1, required=True)
@click.pass_context
def grant(ctx: click.Context, email: str, codenames: tuple[str, ...]) -> int:
    return _dispatch(ctx, "grant", email=email, codenames=list(codenames))


@cli.command(help="Revoke one or more permission codenames from a user.")
@click.argument("email")
@click.argument("codenames", nargs=-1, required=True)
@click.pass_context
def revoke(ctx: click.Context, email: str, codenames: tuple[str, ...]) -> int:
    return _dispatch(ctx, "revoke", email=email, codenames=list(codenames))


@cli.command(help="Show a user's permissions.")
@click.argument("email")
@click.pass_context
def perms(ctx: click.Context, email: str) -> int:
    return _dispatch(ctx, "perms", email=email)


@cli.command(help="Change a password and revoke the user's sessions.")
@click.argument("email")
@click.option("--password-stdin", is_flag=True, help="Read password from standard input.")
@click.pass_context
def changepassword(ctx: click.Context, email: str, password_stdin: bool) -> int:
    return _dispatch(ctx, "changepassword", email=email, password_stdin=password_stdin)


@cli.command(help="Validate configuration, migrations, permissions and indexes.")
@click.pass_context
def check(ctx: click.Context) -> int:
    return _dispatch(ctx, "check")


@cli.command(help="Write a starting admin.py from mapped models.")
@click.option("--models", required=True, help="Model module or module:Base.")
@click.option("--session", help="Your async_sessionmaker as module:name.")
@click.option("--output", help="Destination; defaults beside the models.")
@click.option("--title", default="Admin", show_default=True, help="Title shown in the UI.")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@click.option("--stdout", is_flag=True, help="Print without writing a file.")
@click.pass_context
def init(ctx: click.Context, /, **values: Any) -> int:
    return _dispatch(ctx, "init", **values)


@cli.command(help="Run a seeded local shop; install oneadmin[demo] first.")
@click.option("--rows", type=click.IntRange(min=1), default=1_000_000, show_default=True)
@click.option("--database", help="Database URL; defaults to local SQLite.")
@click.option("--port", type=click.IntRange(min=1, max=65535), default=8000, show_default=True)
@click.option("--reset", is_flag=True, help="Re-create the default database.")
@click.option("--no-browser", is_flag=True, help="Keep the browser closed.")
@click.pass_context
def demo(ctx: click.Context, /, **values: Any) -> int:
    return _dispatch(ctx, "demo", **values)


@cli.command(help="Convert another admin's model configuration.")
@click.argument("source", type=click.Choice(["sqladmin"]))
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", help="Write here instead of printing.")
@click.pass_context
def convert(ctx: click.Context, source: str, file: str, output: str | None) -> int:
    return _dispatch(ctx, "convert", source=source, file=file, output=output)


@cli.command(help="Show resolved model or field settings and their origins.")
@click.argument("target", metavar="MODEL[.FIELD]")
@click.pass_context
def explain(ctx: click.Context, target: str) -> int:
    return _dispatch(ctx, "explain", target=target)


@cli.command(help="Print the compiled configuration as JSON.")
@click.option("--diff", "diff", metavar="FILE", help="Compare with an earlier schema file.")
@click.pass_context
def schema(ctx: click.Context, diff: str | None) -> int:
    return _dispatch(ctx, "schema", diff=diff)


def _init(args: Any, console: Console) -> int:
    from oneadmin.cli.init import init  # noqa: PLC0415

    return init(args, console)


def _demo(args: Any, console: Console) -> int:
    from oneadmin.cli.demo import demo  # noqa: PLC0415

    return demo(args, console)


def _convert(args: Any, console: Console) -> int:
    from oneadmin.cli.convert import convert_sqladmin  # noqa: PLC0415

    try:
        source = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        raise OneAdminError(f"can't read {args.file}: {exc}") from None
    try:
        result = convert_sqladmin(source)
    except SyntaxError as exc:
        raise OneAdminError(f"{args.file} isn't valid Python: {exc}") from None
    if not result.converted:
        raise OneAdminError(f"No sqladmin ModelView classes found in {args.file}.")
    if args.output:
        out = Path(args.output)
        if out.resolve() == Path(args.file).resolve():
            raise OneAdminError("--output must differ from the input file.")
        out.write_text(result.source, encoding="utf-8")
    else:
        console.say(result.source.rstrip("\n"))
    console.warn(
        f"Converted {len(result.converted)} class(es): {', '.join(result.converted)}. "
        f"{result.todos} TODO(oneadmin) note(s) to review."
    )
    return 0


SITELESS: dict[str, Callable[[Any, Console], int]] = {
    "convert": _convert,
    "init": _init,
    "demo": _demo,
}


def main(argv: Sequence[str] | None = None, *, console: Console | None = None) -> int:
    """Entry point. Returns the process exit code."""
    console = console or Console()
    try:
        result = cli.main(
            args=list(argv) if argv is not None else None,
            prog_name="oneadmin",
            standalone_mode=False,
            obj=console,
        )
        return int(result or 0)
    except click.ClickException as exc:
        exc.show(file=console.stderr)
        return exc.exit_code
    except OneAdminError as exc:
        console.warn(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        console.warn("\naborted")
        return 130
