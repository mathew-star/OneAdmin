"""Whitelisted column filters.

Wire format (query string): ``f.<field>`` or ``f.<field>__<op>`` = value.
Example: ``f.status__in=paid,shipped&f.total__gte=10&f.shipped_at__isnull=true``.

Each value is parsed by the column's ``FieldType`` and bound as a parameter. The
operators a column allows come from its field type (``FieldType.filter_ops``).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.sql.elements import ColumnElement

from oneadmin.core.coerce import parse_text
from oneadmin.core.errors import InvalidFilter
from oneadmin.core.meta import FieldMeta, ModelMeta

PREFIX = "f."
MAX_FILTERS = 20
MAX_IN_VALUES = 100


@dataclass(frozen=True, slots=True)
class FilterClause:
    field: FieldMeta
    op: str
    value: Any


def _split(key: str) -> tuple[str, str]:
    body = key[len(PREFIX) :]
    name, sep, op = body.rpartition("__")
    return (name, op) if sep else (body, "eq")


def parse_filters(
    meta: ModelMeta, params: Iterable[tuple[str, str]], *, allowed: Collection[str]
) -> list[FilterClause]:
    """Parse ``(key, value)`` pairs. Keys not starting with ``f.`` are ignored."""
    clauses: list[FilterClause] = []
    for key, raw in params:
        if not key.startswith(PREFIX):
            continue
        if len(clauses) >= MAX_FILTERS:
            raise InvalidFilter(f"at most {MAX_FILTERS} filters are allowed", param=key)
        name, op = _split(key)
        if name not in allowed or name not in meta.fields:
            raise InvalidFilter(f"cannot filter by {name!r}", param=key)
        field = meta.fields[name]
        if op == "isnull":
            if not field.nullable:
                raise InvalidFilter(f"{name!r} is not nullable", param=key)
            value: Any = _bool(raw, key)
        elif op not in field.field_type.filter_ops:
            raise InvalidFilter(f"operator {op!r} is not supported for {name!r}", param=key)
        elif op == "in":
            parts = [p for p in raw.split(",") if p != ""]
            if not parts or len(parts) > MAX_IN_VALUES:
                raise InvalidFilter(f"'in' takes 1 to {MAX_IN_VALUES} values", param=key)
            value = tuple(_parse(field, p, key) for p in parts)
        elif op in ("contains", "icontains", "startswith", "istartswith"):
            if raw == "":
                raise InvalidFilter("empty text filter", param=key)
            if len(raw) > 1_000:
                raise InvalidFilter("text filter longer than 1000 characters", param=key)
            value = raw
        else:
            value = _parse(field, raw, key)
        clauses.append(FilterClause(field, op, value))
    return clauses


def _parse(field: FieldMeta, raw: str, key: str) -> Any:
    try:
        return parse_text(field, raw)
    except ValueError as exc:
        raise InvalidFilter(f"{field.name}: {exc}", param=key) from None


def _bool(raw: str, key: str) -> bool:
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise InvalidFilter("isnull takes true or false", param=key)


def to_sql(clause: FilterClause) -> ColumnElement[bool]:
    e: ColumnElement[Any] = clause.field.expr
    v = clause.value
    match clause.op:
        case "eq":
            return _b(e == v)
        case "ne":
            # SQL ``<>`` drops NULL rows; "not equal" in an admin UI should keep them.
            return _b((e != v) | e.is_(None)) if clause.field.nullable else _b(e != v)
        case "gt":
            return _b(e > v)
        case "gte":
            return _b(e >= v)
        case "lt":
            return _b(e < v)
        case "lte":
            return _b(e <= v)
        case "in":
            return e.in_(v)
        case "isnull":
            return e.is_(None) if v else e.is_not(None)
        case "contains":
            return e.contains(v, autoescape=True)
        case "icontains":
            return e.icontains(v, autoescape=True)
        case "startswith":
            return e.startswith(v, autoescape=True)
        case "istartswith":
            return e.istartswith(v, autoescape=True)
    raise AssertionError(f"unhandled filter op {clause.op}")  # pragma: no cover


def _b(expr: Any) -> ColumnElement[bool]:
    """Narrow SQLAlchemy's loosely typed comparison results for mypy."""
    out: ColumnElement[bool] = expr
    return out
