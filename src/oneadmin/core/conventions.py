"""Site-wide conventions: rules that configure every matching model and field (ADR-0020).

Instead of repeating an option on 200 ``ModelAdmin`` classes, state it once::

    from oneadmin import conventions as cv

    admin = AdminSite(
        ...,
        conventions=[
            cv.readonly(r".*_at", id="timestamps"),
            cv.hide(r".*_secret"),
            cv.field_type(EmailField(), name=r"(.*_)?email"),
            cv.filterable(kind=("boolean", "enum")),
            cv.scope_by("tenant_id", lambda ctx: ctx.identity.extra.get("tenant_id")),
        ],
    )

**Precedence**, lowest to highest:
1. defaults from the model
2. conventions, in the order given (a later one wins over an earlier one)
3. the ``ModelAdmin``'s own options

An admin opts out of a convention by its ``id``: ``ignore_conventions = ("timestamps",)``.

Every convention remembers where it was declared. ``oneadmin explain`` shows which rule set
which value, so a large configuration stays debuggable.

**Field criteria** are combined with AND, and at least one is required:
- ``name``: a regular expression that must match the whole attribute name
- ``kind``: one kind or a tuple of kinds (``"string"``, ``"datetime"``...)
- ``models``: only these model classes
- ``where``: ``(model, field) -> bool`` for anything else
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from oneadmin.core.errors import ConfigurationError
from oneadmin.core.fields import FieldType

if TYPE_CHECKING:
    from oneadmin.core.context import AdminContext
    from oneadmin.core.meta import FieldMeta


# ---- origins (provenance) -----------------------------------------------------------------
OriginKind = Literal["default", "model", "convention", "option"]


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a resolved setting came from, for ``oneadmin explain``."""

    kind: OriginKind
    detail: str = ""

    def __str__(self) -> str:
        match self.kind:
            case "default":
                return f"default ({self.detail})" if self.detail else "default"
            case "model":
                return f"model: {self.detail}"
            case "convention":
                return f"convention {self.detail}"
            case "option":
                return self.detail


DEFAULT = Origin("default")


# ---- scoping ------------------------------------------------------------------------------
class _All:
    """The "no restriction" scope value. Use ``conventions.ALL``."""

    _instance: _All | None = None

    def __new__(cls) -> _All:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ALL"


ALL: Any = _All()
"""Return this from a ``scope_by`` value function to see every row (e.g. platform staff)."""

ScopeValue = Callable[["AdminContext"], Any]
"""``(ctx) -> value``, sync or async. A collection means "any of these"; ``ALL`` means no
restriction; ``None`` means **no rows** (fail closed: a missing tenant never sees everything)."""


# ---- rules --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Convention:
    """Base class of every convention. Create them with the functions in this module."""

    id: str
    """Name used by ``ModelAdmin.ignore_conventions`` and shown by ``explain``."""
    declared_at: str
    """``file:line`` where the convention was created."""

    @property
    def origin(self) -> Origin:
        return Origin("convention", f"{self.id} ({self.declared_at})")


@dataclass(frozen=True, slots=True)
class FieldConvention(Convention):
    """A convention applied to every matching field of every model."""

    action: Literal["readonly", "hide", "field_type", "label", "filterable"] = "readonly"
    name: re.Pattern[str] | None = None
    kinds: frozenset[str] | None = None
    models: frozenset[type[Any]] | None = None
    where: Callable[[type[Any], FieldMeta], bool] | None = None
    value: Any = None
    """The field type (``field_type``) or the label (``label``)."""

    def matches(self, model: type[Any], f: FieldMeta) -> bool:
        if self.name is not None and not self.name.fullmatch(f.name):
            return False
        if self.kinds is not None and f.kind not in self.kinds:
            return False
        if self.models is not None and not any(issubclass(model, m) for m in self.models):
            return False
        return self.where is None or bool(self.where(model, f))


@dataclass(frozen=True, slots=True)
class ScopeBy(Convention):
    """Restrict every model that has ``column`` to the rows matching ``value(ctx)``."""

    column: str = ""
    value: ScopeValue = field(default=lambda ctx: ALL)
    autofill: bool = True
    """On create, set ``column`` from the scope when the client didn't send it."""

    async def resolve(self, ctx: AdminContext) -> Any:
        result = self.value(ctx)
        if inspect.isawaitable(result):
            result = await result
        return result


# ---- factories ----------------------------------------------------------------------------
Kinds = str | Collection[str] | None


def readonly(
    name: str | None = None,
    *,
    kind: Kinds = None,
    models: Iterable[type[Any]] | None = None,
    where: Callable[[type[Any], FieldMeta], bool] | None = None,
    id: str | None = None,
) -> FieldConvention:
    """Make matching fields read-only, e.g. ``readonly(r".*_at")``."""
    return _field_rule("readonly", None, name, kind, models, where, id)


def hide(
    name: str | None = None,
    *,
    kind: Kinds = None,
    models: Iterable[type[Any]] | None = None,
    where: Callable[[type[Any], FieldMeta], bool] | None = None,
    id: str | None = None,
) -> FieldConvention:
    """Never send matching fields to clients, e.g. ``hide(r".*_secret")``."""
    return _field_rule("hide", None, name, kind, models, where, id)


def field_type(
    type_: FieldType,
    name: str | None = None,
    *,
    kind: Kinds = None,
    models: Iterable[type[Any]] | None = None,
    where: Callable[[type[Any], FieldMeta], bool] | None = None,
    id: str | None = None,
) -> FieldConvention:
    """Use ``type_`` for matching fields, e.g. ``field_type(EmailField(), r".*email")``."""
    if not isinstance(type_, FieldType):
        raise ConfigurationError(f"field_type() needs a FieldType instance, got {type_!r}")
    return _field_rule("field_type", type_, name, kind, models, where, id)


def label(
    text: str,
    name: str | None = None,
    *,
    kind: Kinds = None,
    models: Iterable[type[Any]] | None = None,
    where: Callable[[type[Any], FieldMeta], bool] | None = None,
    id: str | None = None,
) -> FieldConvention:
    """Label matching fields, e.g. ``label("Created", "created_at")``."""
    return _field_rule("label", text, name, kind, models, where, id)


def filterable(
    name: str | None = None,
    *,
    kind: Kinds = None,
    models: Iterable[type[Any]] | None = None,
    where: Callable[[type[Any], FieldMeta], bool] | None = None,
    id: str | None = None,
) -> FieldConvention:
    """Allow list filters on matching fields, e.g. ``filterable(kind=("boolean", "enum"))``.

    Fields whose type has no filter operators (JSON, binary) are skipped silently.
    """
    return _field_rule("filterable", None, name, kind, models, where, id)


def scope_by(
    column: str,
    value: ScopeValue,
    *,
    autofill: bool = True,
    id: str | None = None,
) -> ScopeBy:
    """Scope every model that has ``column`` (a mapped attribute name) by ``value(ctx)``.

    Applies to every read and write, together with each admin's own ``get_queryset``::

        cv.scope_by("tenant_id", lambda ctx: ctx.identity.extra.get("tenant_id", ALL))

    ``value`` returns the allowed value, a collection of allowed values, ``ALL`` for no
    restriction, or ``None``, which matches **no rows**. The fail-closed default means a
    user without a tenant never sees every tenant. With ``autofill`` (the default), new
    rows get ``column`` set from a single scope value when the client omits it.
    """
    if not column or not callable(value):
        raise ConfigurationError("scope_by(column, value): value must be a callable (ctx) -> ...")
    return ScopeBy(
        id=id or f"scope_by({column!r})",
        declared_at=_caller(),
        column=column,
        value=value,
        autofill=autofill,
    )


def _field_rule(
    action: Literal["readonly", "hide", "field_type", "label", "filterable"],
    value: Any,
    name: str | None,
    kind: Kinds,
    models: Iterable[type[Any]] | None,
    where: Callable[[type[Any], FieldMeta], bool] | None,
    id: str | None,
) -> FieldConvention:
    if name is None and kind is None and models is None and where is None:
        raise ConfigurationError(
            f"{action}(): give at least one of name=, kind=, models= or where= "
            "(a convention that matches every field is almost always a mistake)"
        )
    try:
        pattern = re.compile(name) if name is not None else None
    except re.error as exc:
        raise ConfigurationError(f"{action}(): invalid name pattern {name!r}: {exc}") from None
    kinds = frozenset([kind] if isinstance(kind, str) else kind) if kind is not None else None
    criteria = [repr(value) if action == "label" else value.describe()] if value is not None else []
    if name is not None:
        criteria.append(repr(name))
    if kinds is not None:
        criteria.append(f"kind={sorted(kinds)}")
    return FieldConvention(
        id=id or f"{action}({', '.join(criteria) or '...'})",
        declared_at=_caller(),
        action=action,
        name=pattern,
        kinds=kinds,
        models=frozenset(models) if models is not None else None,
        where=where,
        value=value,
    )


def _caller() -> str:
    """``file:line`` of the first frame outside this module: the user's declaration."""
    frame = sys._getframe(1)
    while frame.f_back is not None and frame.f_code.co_filename == __file__:
        frame = frame.f_back
    path = frame.f_code.co_filename
    try:
        path = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        path = os.path.basename(path)
    return f"{path}:{frame.f_lineno}"
