"""Permission codenames (ADR-0019).

``<slug>.view``, ``<slug>.add``, ``<slug>.change``, ``<slug>.delete``,
``<slug>.action.<name>`` for actions with their own permission, and ``<slug>.*`` for all of
one model's permissions. Superusers implicitly hold every permission.
"""

from __future__ import annotations

import re
from typing import Literal

from oneadmin.core.errors import OneAdminError

Operation = Literal["view", "add", "change", "delete"]
OPERATIONS: tuple[Operation, ...] = ("view", "add", "change", "delete")

_CODENAME = re.compile(
    r"[a-z0-9_-]{1,64}\.(?:\*|view|add|change|delete|action\.[A-Za-z_][A-Za-z0-9_]{0,63})"
)


class InvalidCodename(OneAdminError, ValueError):
    """A string that isn't a permission codename."""


def codename(slug: str, operation: Operation) -> str:
    return f"{slug}.{operation}"


def action_codename(slug: str, action: str) -> str:
    return f"{slug}.action.{action}"


def validate_codename(value: str) -> str:
    """Return ``value`` if it is a well-formed codename, else raise ``InvalidCodename``."""
    if not _CODENAME.fullmatch(value):
        raise InvalidCodename(
            f"{value!r} is not a permission codename. Use '<model>.view', '<model>.add', "
            "'<model>.change', '<model>.delete', '<model>.action.<name>' or '<model>.*'."
        )
    return value
