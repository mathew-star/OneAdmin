"""Implementations of the ``oneadmin`` subcommands. Each returns an exit code."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oneadmin.auth import migrate as migrations
from oneadmin.auth.passwords import WeakPassword, validate_password
from oneadmin.auth.permissions import OPERATIONS, action_codename, codename, validate_codename
from oneadmin.auth.service import InvalidEmail, normalize_email
from oneadmin.core.advisor import advise
from oneadmin.core.errors import ConfigurationError, OneAdminError
from oneadmin.core.explain import (
    describe_site,
    diff_descriptions,
    dump,
    explain_field,
    explain_model,
)
from oneadmin.core.model_admin import ModelAdmin
from oneadmin.site import AdminSite

if TYPE_CHECKING:
    from oneadmin.cli import Console

Handler = Callable[[AdminSite, argparse.Namespace, "Console"], Coroutine[Any, Any, int]]
_MAX_PROMPTS = 3


async def run(handler: Handler, site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    """Run one command, then dispose of the engine so the process exits cleanly."""
    try:
        return await handler(site, args, console)
    finally:
        await site.engine.dispose()


async def migrate(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    before = await migrations.current_revision(site.engine)
    if args.downgrade:
        await migrations.downgrade(site.engine, args.downgrade)
    else:
        await migrations.upgrade(site.engine, args.revision)
    after = await migrations.current_revision(site.engine)
    if before == after:
        console.say(f"OneAdmin tables are up to date (revision {after or 'none'}).")
    else:
        console.say(f"OneAdmin tables migrated: {before or 'none'} -> {after or 'none'}.")
    return 0


async def createsuperuser(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    await _require_migrated(site)
    email = args.email or _prompt_email(console)
    password = _read_password(console, email, from_stdin=args.password_stdin)
    identity = await site.auth.create_user(email, password, is_superuser=True)
    console.say(f"Superuser {identity.email} created.")
    return 0


async def createuser(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    """A non-superuser: they see nothing until granted permissions (ADR-0019)."""
    await _require_migrated(site)
    codenames = _known_codenames(site, args.grant)
    email = args.email or _prompt_email(console)
    password = _read_password(console, email, from_stdin=args.password_stdin)
    identity = await site.auth.create_user(email, password, is_superuser=False)
    if codenames:
        await site.auth.grant(identity.email, codenames)
    granted = ", ".join(codenames) if codenames else "none yet (use `oneadmin grant`)"
    console.say(f"User {identity.email} created. Permissions: {granted}.")
    return 0


async def grant(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    await _require_migrated(site)
    added = await site.auth.grant(args.email, _known_codenames(site, args.codenames))
    console.say(f"Granted: {', '.join(added)}." if added else "Nothing new: already granted.")
    console.say("Takes effect on the user's next request.")
    return 0


async def revoke(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    await _require_migrated(site)
    removed = await site.auth.revoke(args.email, _known_codenames(site, args.codenames))
    console.say(f"Revoked {removed} permission(s).")
    return 0


async def perms(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    await _require_migrated(site)
    is_superuser, codenames = await site.auth.permissions_of(args.email)
    if is_superuser:
        console.say(f"{normalize_email(args.email)} is a superuser: every permission.")
    elif codenames:
        console.say("\n".join(codenames))
    else:
        console.say("No permissions. Grant some with `oneadmin grant EMAIL CODENAME...`.")
    return 0


async def changepassword(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    await _require_migrated(site)
    email = normalize_email(args.email)
    password = _read_password(console, email, from_stdin=args.password_stdin)
    await site.auth.set_password(email, password)
    console.say(f"Password changed for {email}. All of their sessions were signed out.")
    return 0


async def check(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    """Exit 1 on configuration errors or missing migrations; index advice alone exits 0."""
    try:
        site.build_app()
    except ConfigurationError as exc:
        console.warn(f"error: {exc}")
        return 1
    console.say(f"{len(site.admins())} model(s) registered:")
    for admin in site.admins():
        c = admin.compiled
        console.say(f"  /{c.slug:<24} {c.model.__module__}.{c.model.__qualname__}")
        console.say(f"    permissions: {' '.join(model_codenames(admin))}")

    status = 0
    if site.uses_builtin_auth:
        current = await migrations.current_revision(site.engine)
        head = migrations.head_revision()
        if current != head:
            console.warn(
                f"error: OneAdmin tables are at {current or 'none'}, expected {head}. "
                "Run `oneadmin migrate`."
            )
            status = 1
        elif await site.auth.count_superusers() == 0:
            console.warn("warning: no active superuser yet. Run `oneadmin createsuperuser`.")

    advice = advise(site.admins())
    if advice:
        console.say(
            "\nIndex advice (keyset pagination needs an index that starts with the column):"
        )
        for item in advice:
            console.say(f"  - {item}")
    else:
        console.say("\nNo index advice: every sortable and filterable column is indexed.")
    return status


async def explain(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    """Print a model's (or field's) resolved configuration with the origin of each value."""
    site.build_app()
    slug, _, field = args.target.partition(".")
    admin = site.admin_by_slug(slug)
    if admin is None:
        models = ", ".join(a.compiled.slug for a in site.admins())
        raise OneAdminError(f"No model {slug!r} is registered. Models: {models}.")
    lines = explain_field(admin, field) if field else explain_model(admin)
    console.say("\n".join(lines))
    return 0


async def schema(site: AdminSite, args: argparse.Namespace, console: Console) -> int:
    """Print the configuration as JSON; with ``--diff``, print what changed and exit 1 if
    anything did (handy in CI to require reviewing admin changes)."""
    site.build_app()
    current = describe_site(site.admins())
    if not args.diff:
        console.say(dump(current).rstrip("\n"))
        return 0
    try:
        # A CLI command owns its event loop; a small blocking read is fine here.
        previous = json.loads(Path(args.diff).read_text(encoding="utf-8"))  # noqa: ASYNC240
    except (OSError, ValueError) as exc:
        raise OneAdminError(f"can't read {args.diff}: {exc}") from None
    changes = diff_descriptions(previous, current)
    console.say("\n".join(changes) if changes else "No configuration changes.")
    return 1 if changes else 0


# ---- helpers -----------------------------------------------------------------------------
def model_codenames(admin: ModelAdmin) -> list[str]:
    """Every codename that means something for ``admin`` (for `check` and validation)."""
    c = admin.compiled
    names = [codename(c.slug, op) for op in OPERATIONS]
    names += [
        action_codename(c.slug, a.name) for a in c.actions.values() if a.permission == "custom"
    ]
    return [*names, f"{c.slug}.*"]


def _known_codenames(site: AdminSite, codenames: list[str]) -> list[str]:
    """Validate codenames against the registered models, catching typos before they're stored."""
    site.build_app()
    known = {name for admin in site.admins() for name in model_codenames(admin)}
    for name in codenames:
        validate_codename(name)
        if name in known:
            continue
        slug = name.partition(".")[0]
        admin = site.admin_by_slug(slug)
        if admin is None:
            models = ", ".join(sorted(a.compiled.slug for a in site.admins()))
            raise OneAdminError(f"No model {slug!r} is registered. Models: {models}.")
        valid = " ".join(model_codenames(admin))
        raise OneAdminError(f"{name!r} doesn't exist. Valid for {slug!r}: {valid}")
    return codenames


async def _require_migrated(site: AdminSite) -> None:
    if await migrations.current_revision(site.engine) is None:
        raise OneAdminError("OneAdmin's tables don't exist yet. Run `oneadmin migrate` first.")


def _prompt_email(console: Console) -> str:
    if not console.interactive:
        raise OneAdminError("--email is required when not running in a terminal.")
    for _ in range(_MAX_PROMPTS):
        try:
            return normalize_email(console.input("Email: "))
        except InvalidEmail as exc:
            console.warn(str(exc))
    raise OneAdminError("No valid email entered.")


def _read_password(console: Console, email: str, *, from_stdin: bool) -> str:
    if from_stdin:
        password = console.stdin.readline().rstrip("\r\n")
        validate_password(password, email=email)
        return password
    if not console.interactive:
        raise OneAdminError(
            "Not running in a terminal. Pass --password-stdin and pipe the password in."
        )
    for _ in range(_MAX_PROMPTS):
        password = console.getpass("Password: ")
        try:
            validate_password(password, email=email)
        except WeakPassword as exc:
            console.warn(str(exc))
            continue
        if console.getpass("Password (again): ") != password:
            console.warn("Passwords didn't match.")
            continue
        return password
    raise OneAdminError("No acceptable password entered.")
