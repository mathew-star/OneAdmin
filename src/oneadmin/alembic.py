"""Helpers for the host application's own Alembic setup.

Alembic autogenerate proposes **dropping** every table in the database that isn't in the
app's metadata. Once ``oneadmin migrate`` has run, that includes OneAdmin's tables (verified,
docs/research/technical-findings.md §10). Add this to the app's ``alembic/env.py``::

    from oneadmin.alembic import include_object

    context.configure(..., include_object=include_object)

If the app already has an ``include_object``, combine them::

    from oneadmin.alembic import is_oneadmin_object

    def include_object(obj, name, type_, reflected, compare_to):
        if is_oneadmin_object(name, type_):
            return False
        return my_rules(obj, name, type_, reflected, compare_to)
"""

from __future__ import annotations

from typing import Any

from oneadmin.auth.tables import PREFIX, VERSION_TABLE

__all__ = ["include_object", "is_oneadmin_object"]


def is_oneadmin_object(name: str | None, type_: str) -> bool:
    """True for OneAdmin's tables (and their indexes/constraints) and its version table."""
    if name is None:
        return False
    if type_ == "table":
        return name.startswith(PREFIX) or name == VERSION_TABLE
    return name.startswith((PREFIX, f"ix_{PREFIX}", f"uq_{PREFIX}", f"fk_{PREFIX}", f"pk_{PREFIX}"))


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic ``include_object`` hook that leaves OneAdmin's objects alone."""
    return not is_oneadmin_object(name, type_)
