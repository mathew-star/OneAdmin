"""Bulk actions: methods on a ``ModelAdmin`` that act on selected rows (ADR-0018/0019).

Declare one with the ``@action`` decorator::

    class PostAdmin(ModelAdmin):
        @action(label="Publish", confirm="Publish the selected posts?")
        async def publish(self, ctx: AdminContext, rows: list[Post]) -> str | None:
            for post in rows:
                post.published = True
            return f"Published {len(rows)} posts."

The engine loads the rows through ``get_queryset`` (``FOR UPDATE``), checks the permission
for every row, runs the method in the request's transaction, re-checks that every row is
still in scope, writes one audit entry per changed row, then commits. A message returned
by the method is shown to the user.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from oneadmin.auth.permissions import Operation

ActionPermission = Operation | Literal["custom"]
"""Which permission an action needs on every selected row. ``"custom"`` means the action's
own codename, ``<slug>.action.<name>``, so it can be granted separately."""

F = TypeVar("F", bound=Callable[..., Awaitable[str | None]])

MAX_ACTION_ROWS = 1_000
DELETE_SELECTED = "delete_selected"
_MARKER = "__oneadmin_action__"


@dataclass(frozen=True, slots=True)
class ActionOptions:
    label: str | None
    confirm: str | None
    permission: ActionPermission
    destructive: bool


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """A compiled action of one admin."""

    name: str
    label: str
    confirm: str | None
    permission: ActionPermission
    destructive: bool
    method: str | None
    """Name of the ``ModelAdmin`` method; ``None`` for the built-in ``delete_selected``."""


def action(
    *,
    label: str | None = None,
    confirm: str | None = None,
    permission: ActionPermission = "change",
    destructive: bool = False,
) -> Callable[[F], F]:
    """Mark an ``async def name(self, ctx, rows) -> str | None`` method as a bulk action.

    Args:
        label: Button text. Default: the method name in words.
        confirm: If set, the UI asks this question before running the action.
        permission: Needed on every selected row: ``"view"``, ``"add"``, ``"change"``
            (default), ``"delete"``, or ``"custom"`` for the codename
            ``<slug>.action.<name>``.
        destructive: Styles the action as dangerous in the UI.
    """

    def decorate(func: F) -> F:
        setattr(func, _MARKER, ActionOptions(label, confirm, permission, destructive))
        return func

    return decorate


def declared_actions(admin_cls: type[Any]) -> dict[str, ActionOptions]:
    """``{method name: options}`` of every ``@action`` on the class and its bases."""
    found: dict[str, ActionOptions] = {}
    for klass in reversed(admin_cls.__mro__):
        for name, value in vars(klass).items():
            options = getattr(value, _MARKER, None)
            if isinstance(options, ActionOptions):
                found[name] = options
    return found
