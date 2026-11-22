"""Keyset ("seek") predicate compiler. See ADR-0003 and technical-findings §2.

The key rule, measured on PG17 over 1M rows: never emit only
``k1 > v1 OR (k1 = v1 AND k2 > v2)``. The planner treats it as a Filter, which costs the
same as OFFSET. Every predicate here has a sargable leading bound:

* **row-value** ``(k1, k2) > (v1, v2)``: all keys share one direction. An Index Cond on
  the row, which seeks directly even when ``k1`` has few distinct values.
* **bounded nested** ``k1 >= v1 AND (k1 > v1 OR (k2 >= v2 AND (...)))``: mixed
  directions. An Index Cond on ``k1 >= v1``.

A nullable *leading* key yields up to two ordered **segments** (non-null range, NULL range).
The caller runs them as a ``UNION ALL`` of individually LIMITed branches, each of them
index-friendly. Sorts with a nullable *non-leading* key use offset mode instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import and_, literal, or_, tuple_
from sqlalchemy.sql.elements import ColumnElement

from oneadmin.core.query.sorting import SortKey, SortSpec

#: Dialects whose row-value comparisons compile and are planned as index range scans.
ROW_VALUE_DIALECTS = frozenset({"postgresql", "sqlite"})

PaginationMode = Literal["keyset", "offset"]


def pagination_mode(sort: SortSpec) -> PaginationMode:
    if any(k.field.nullable for k in sort.keys[1:]):
        return "offset"
    return "keyset"


def _cmp(key: SortKey, value: Any, *, strict: bool) -> ColumnElement[bool]:
    e = key.field.expr
    out: ColumnElement[bool]
    if key.descending:
        out = e < value if strict else e <= value
    else:
        out = e > value if strict else e >= value
    return out


def _after(
    keys: Sequence[SortKey], values: Sequence[Any], *, row_values: bool
) -> ColumnElement[bool]:
    """Rows strictly after ``values`` in the order of ``keys``. All ``values`` are non-null."""
    if len(keys) == 1:
        return _cmp(keys[0], values[0], strict=True)
    if row_values and len({k.descending for k in keys}) == 1:
        lhs = tuple_(*(k.field.expr for k in keys))
        rhs = tuple_(*(literal(v, k.field.column.type) for k, v in zip(keys, values, strict=True)))
        return lhs < rhs if keys[0].descending else lhs > rhs
    pred = _cmp(keys[-1], values[-1], strict=True)
    for key, value in zip(reversed(keys[:-1]), reversed(values[:-1]), strict=True):
        pred = and_(_cmp(key, value, strict=False), or_(_cmp(key, value, strict=True), pred))
    return pred


def keyset_segments(
    sort: SortSpec, values: Sequence[Any], *, dialect: str
) -> list[ColumnElement[bool]]:
    """Predicates selecting rows after ``values`` under ``sort``, as ordered segments."""
    if pagination_mode(sort) != "keyset":
        raise ValueError("sort requires offset pagination")
    keys = sort.keys
    row_values = dialect in ROW_VALUE_DIALECTS
    lead, lead_value = keys[0], values[0]
    if not lead.field.nullable:
        return [_after(keys, values, row_values=row_values)]
    col = lead.field.expr
    rest, rest_values = keys[1:], values[1:]
    if lead_value is None:
        in_nulls = and_(col.is_(None), _after(rest, rest_values, row_values=row_values))
        if lead.nulls_last:
            return [in_nulls]
        return [in_nulls, col.is_not(None)]
    in_values = _after(keys, values, row_values=row_values)  # NULL lead rows never match
    if lead.nulls_last:
        return [in_values, col.is_(None)]
    return [in_values]
