"""Source-level checks of CLAUDE.md invariants that types can't express."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "oneadmin"


def test_only_apply_scope_calls_get_queryset() -> None:
    """Invariant 4: every path scopes through apply_scope (conventions + get_queryset).

    A direct get_queryset() call would skip scope_by conventions, i.e. tenant isolation.
    """
    offenders = [
        f"{path.relative_to(SRC)}:{n}"
        for path in SRC.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.get_queryset\(", line)
        and not line.lstrip().startswith(("#", '"'))
        and path.name != "model_admin.py"
    ]
    assert offenders == [], f"call apply_scope() instead: {offenders}"


def test_per_kind_rules_live_only_in_fields() -> None:
    """Invariant 13: no module outside core/fields.py branches on a column's kind to parse
    or encode values (display decisions such as default list columns are allowed)."""
    pattern = re.compile(r"match (field|f)\.kind|case \"(decimal|integer|datetime)\"")
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if path.name != "fields.py" and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
