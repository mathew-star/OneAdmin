"""Enforce the dependency direction documented in CLAUDE.md / PLAN §2."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "oneadmin"

FORBIDDEN: dict[str, tuple[str, ...]] = {
    # ADR-0017: the HTTP layer sees only ORM-neutral service results.
    "api": ("sqlalchemy",),
    "core": (
        "fastapi",
        "starlette",
        "oneadmin.api",
        "oneadmin.ui",
        "oneadmin.cli",
        "oneadmin.site",
    ),
    "auth": (
        "fastapi",
        "starlette",
        "oneadmin.api",
        "oneadmin.ui",
        "oneadmin.cli",
        "oneadmin.site",
    ),
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def violations(layer: str) -> list[str]:
    out = []
    for py in sorted((SRC / layer).rglob("*.py")):
        for mod in imported_modules(py):
            if any(mod == bad or mod.startswith(bad + ".") for bad in FORBIDDEN[layer]):
                out.append(f"{py.relative_to(SRC)} imports {mod}")
    return out


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_does_not_import_web_or_outer_layers(layer: str) -> None:
    assert violations(layer) == []


def test_checker_detects_violation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("from fastapi import Request\nimport starlette.responses\n")
    assert imported_modules(bad) == {"fastapi", "starlette.responses"}
