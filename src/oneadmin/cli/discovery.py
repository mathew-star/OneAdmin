"""Find the application's ``AdminSite``, the way uvicorn finds an app.

Resolution order:

1. ``--app module.path:attribute``
2. the ``ONEADMIN_APP`` environment variable
3. ``[tool.oneadmin] app = "module.path:attribute"`` in the nearest ``pyproject.toml``
"""

from __future__ import annotations

import importlib
import os
import sys
import tomllib
from pathlib import Path
from types import ModuleType

from oneadmin.core.errors import ConfigurationError
from oneadmin.site import AdminSite

ENV_VAR = "ONEADMIN_APP"
_HOW = (
    "Tell OneAdmin where your AdminSite is: pass --app app.admin:admin, set "
    f"{ENV_VAR}=app.admin:admin, or add to pyproject.toml:\n\n"
    '    [tool.oneadmin]\n    app = "app.admin:admin"'
)


def find_pyproject(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def resolve_reference(explicit: str | None, cwd: Path) -> str:
    if explicit:
        return explicit
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    pyproject = find_pyproject(cwd)
    if pyproject is not None:
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        ref = config.get("tool", {}).get("oneadmin", {}).get("app")
        if isinstance(ref, str) and ref:
            return ref
    raise ConfigurationError(f"No AdminSite configured. {_HOW}")


def load_site(reference: str, cwd: Path) -> AdminSite:
    """Import ``module:attribute`` and return the ``AdminSite`` it names."""
    module_name, sep, attribute = reference.partition(":")
    if not sep or not module_name or not attribute:
        raise ConfigurationError(f"{reference!r} is not in 'module.path:attribute' form. {_HOW}")
    module = import_project_module(module_name, cwd)
    site = getattr(module, attribute, None)
    if not isinstance(site, AdminSite):
        found = type(site).__name__ if site is not None else "nothing"
        raise ConfigurationError(f"{reference} is {found}, expected an AdminSite instance.")
    return site


def import_project_module(module_name: str, cwd: Path) -> ModuleType:
    """Import a module of the user's project, run from its root (flat or ``src/`` layout)."""
    for path in (cwd, cwd / "src"):  # like uvicorn's --app-dir, plus the src/ layout
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            f"Could not import {module_name!r} ({exc}). Run oneadmin from your project root, "
            "inside the project's environment (e.g. `uv run oneadmin ...`)."
        ) from exc
