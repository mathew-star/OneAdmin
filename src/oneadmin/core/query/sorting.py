"""Sort specifications: parse, validate against an allow-list, and complete with the PK."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.sql.elements import UnaryExpression

from oneadmin.core.errors import ConfigurationError, InvalidSort
from oneadmin.core.meta import FieldMeta, ModelMeta

MAX_SORT_KEYS = 4


@dataclass(frozen=True, slots=True)
class SortKey:
    field: FieldMeta
    descending: bool
    nulls_last: bool
    """Ignored for non-nullable fields. The default follows PostgreSQL: ASC→LAST, DESC→FIRST."""

    @classmethod
    def of(cls, field: FieldMeta, *, descending: bool) -> SortKey:
        return cls(field=field, descending=descending, nulls_last=not descending)

    def reversed(self) -> SortKey:
        return SortKey(self.field, not self.descending, not self.nulls_last)

    def order_by(self, expr: Any | None = None) -> UnaryExpression[Any]:
        e = self.field.expr if expr is None else expr
        clause = e.desc() if self.descending else e.asc()
        if self.field.nullable:  # only emit NULLS ... where it matters (and is portable)
            clause = clause.nulls_last() if self.nulls_last else clause.nulls_first()
        return clause

    def token(self) -> str:
        return ("-" if self.descending else "") + self.field.name


@dataclass(frozen=True, slots=True)
class SortSpec:
    keys: tuple[SortKey, ...]

    @property
    def signature(self) -> str:
        """Binds cursors to the sort they were produced under."""
        raw = ",".join(f"{k.token()}:{int(k.nulls_last)}" for k in self.keys)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def uniform(self) -> bool:
        return len({k.descending for k in self.keys}) == 1

    def reversed(self) -> SortSpec:
        return SortSpec(tuple(k.reversed() for k in self.keys))

    def order_by(self) -> list[UnaryExpression[Any]]:
        return [k.order_by() for k in self.keys]


def parse_sort(
    meta: ModelMeta,
    spec: str | Sequence[str] | None,
    *,
    allowed: Collection[str],
    default: Sequence[str] = (),
) -> SortSpec:
    """Parse ``"-created_at,name"`` (or a sequence of tokens).

    Unknown, disallowed, unsortable or duplicate fields raise ``InvalidSort``. The result is
    completed with every PK column so the order is total. Appended PK columns inherit the
    direction of the last explicit key, which keeps the common case uniform and so eligible
    for row-value keyset predicates.
    """
    tokens = _tokens(spec) or list(default)
    if len(tokens) > MAX_SORT_KEYS:
        raise InvalidSort(f"at most {MAX_SORT_KEYS} sort keys are allowed", param="sort")
    keys: list[SortKey] = []
    seen: set[str] = set()
    for token in tokens:
        descending = token.startswith("-")
        name = token[1:] if descending else token
        if name not in allowed or name not in meta.fields:
            raise InvalidSort(f"cannot sort by {name!r}", param="sort")
        field = meta.fields[name]
        if not field.sortable:
            raise InvalidSort(f"{name!r} is not sortable", param="sort")
        if name in seen:
            raise InvalidSort(f"duplicate sort key {name!r}", param="sort")
        seen.add(name)
        keys.append(SortKey.of(field, descending=descending))
    tail_desc = keys[-1].descending if keys else False
    for pk in meta.pk:
        if pk.name not in seen:
            keys.append(SortKey.of(pk, descending=tail_desc))
    return SortSpec(tuple(keys))


def validate_default_sort(meta: ModelMeta, default: Sequence[str]) -> None:
    """Startup check for ``ModelAdmin.ordering``. Raises ``ConfigurationError``."""
    try:
        parse_sort(meta, None, allowed=meta.fields.keys(), default=default)
    except InvalidSort as exc:
        raise ConfigurationError(f"{meta.model.__name__}.ordering: {exc.message}") from None


def _tokens(spec: str | Sequence[str] | None) -> list[str]:
    if spec is None:
        return []
    parts = spec.split(",") if isinstance(spec, str) else list(spec)
    return [p.strip() for p in parts if p.strip()]
