"""Strict conversion between client-supplied values and Python values for a column.

The rules live on each column's ``FieldType`` (``core.fields``, ADR-0020). These functions
are the call sites' stable entry points:

- ``parse_text(field, raw)``: a query-string value (filters, search, PKs) to a typed value.
- ``to_json`` / ``from_json``: lossless JSON encoding of sort-key values inside cursors.

Every failure raises ``ValueError`` with a client-safe message. Callers wrap it in the
relevant ``QueryError`` subclass.
"""

from __future__ import annotations

from typing import Any

from oneadmin.core.fields import (
    MAX_TEXT_LENGTH,
    check_precision,
    parse_datetime,
    to_cursor_json,
)
from oneadmin.core.meta import FieldMeta

__all__ = [
    "MAX_TEXT_LENGTH",
    "check_precision",
    "from_json",
    "parse_datetime",
    "parse_text",
    "to_json",
]


def parse_text(field: FieldMeta, raw: str) -> Any:
    """Parse one textual value for ``field``. Raises ``ValueError`` on bad input."""
    return field.field_type.parse_text(field, raw)


def to_json(value: Any, field: FieldMeta | None = None) -> Any:
    """Encode a sort-key value for a cursor (by its field's type when known)."""
    if field is None or value is None:
        return to_cursor_json(value)
    return field.field_type.to_cursor(value)


def from_json(field: FieldMeta, raw: Any) -> Any:
    """Decode a cursor value for ``field``. Raises ``ValueError`` if the shape is wrong."""
    if raw is None:
        if not field.nullable:
            raise ValueError("null value for a non-nullable sort key")
        return None
    return field.field_type.from_cursor(field, raw)
