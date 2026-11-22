"""``oneadmin init``: the command around ``scaffold`` (argument handling and messages)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from oneadmin.cli import scaffold
from oneadmin.cli.discovery import import_project_module
from oneadmin.core.errors import OneAdminError

if TYPE_CHECKING:
    from oneadmin.cli import Console


def init(args: argparse.Namespace, console: Console) -> int:
    cwd = Path.cwd()
    module_name, _, attribute = args.models.partition(":")
    module = import_project_module(module_name, cwd)
    models = scaffold.mapped_classes(module, attribute or None)
    root = module_name.split(".")[0]
    session = args.session or scaffold.find_session_factory(root)
    if session is None:
        raise OneAdminError(
            f"No async_sessionmaker found in {root}.database, {root}.db or similar. "
            "Pass --session module:name (e.g. --session app.database:async_session_maker)."
        )
    output, admin_module = scaffold.default_output(module)
    if args.output:
        output = Path(args.output)
        admin_module = _module_of(output, cwd)
    source = scaffold.render(
        models, models_module=module, admin_module=admin_module, session=session, title=args.title
    )
    if args.stdout:
        console.say(source.rstrip("\n"))
        return 0
    scaffold.write(output, source, force=args.force)
    shown = output.relative_to(cwd) if output.is_relative_to(cwd) else output
    console.say(f"Wrote {shown}: {len(models)} model(s), session factory {session}.")
    console.say("")
    console.say("Next steps:")
    console.say(
        f'  1. In your FastAPI app:  from {admin_module} import admin; admin.mount(app, path="/admin")'
    )
    console.say(f'  2. In pyproject.toml:     [tool.oneadmin] app = "{admin_module}:admin"')
    console.say("  3. Try it locally:        ONEADMIN_DEV=1 uvicorn ...  then open /admin/")
    console.say("     (for production: oneadmin migrate && oneadmin createsuperuser)")
    return 0


def _module_of(path: Path, cwd: Path) -> str:
    resolved = path.resolve()
    for root in (cwd / "src", cwd):
        if resolved.is_relative_to(root.resolve()):
            parts = resolved.relative_to(root.resolve()).with_suffix("").parts
            return ".".join(parts)
    return resolved.stem
