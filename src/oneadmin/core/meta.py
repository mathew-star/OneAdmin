"""Model introspection into immutable metadata.

``introspect(Model)`` runs once per registration. Everything downstream (query engine,
validation, the schema contract) reads ``ModelMeta`` and never re-inspects the mapper on the
request path.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from sqlalchemy import Column, inspect, types
from sqlalchemy.orm import ColumnProperty, InstrumentedAttribute, Mapper
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Computed, Identity

from oneadmin.core.errors import ConfigurationError
from oneadmin.core.fields import FieldKind, FieldType, default_field_type, unwrap

_PY_TYPES: dict[FieldKind, type] = {
    "string": str,
    "text": str,
    "integer": int,
    "decimal": Decimal,
    "float": float,
    "boolean": bool,
    "datetime": datetime,
    "date": date,
    "time": time,
    "interval": timedelta,
    "uuid": uuid.UUID,
}


@dataclass(frozen=True, slots=True)
class FieldMeta:
    """One mapped column attribute, as the admin sees it."""

    name: str
    attribute: InstrumentedAttribute[Any]
    column: Column[Any]
    field_type: FieldType
    """Decides wire format, parsing, filters, sortability and widget (ADR-0020)."""
    python_type: type | None
    nullable: bool
    primary_key: bool
    max_length: int | None
    enum_class: type[enum.Enum] | None
    enum_values: tuple[str, ...] | None
    tz_aware: bool
    has_default: bool
    generated: bool
    """Computed/Identity/autoincrement-PK columns. These are never writable by clients."""
    auto_updated: bool = False
    """Has ``onupdate``/``server_onupdate`` (e.g. ``updated_at``): set by the app or database
    on every update, so it is read-only in the admin."""

    @property
    def kind(self) -> FieldKind:
        """The semantic base kind the API and UI branch on (from the field type)."""
        return self.field_type.kind

    @property
    def sortable(self) -> bool:
        return self.field_type.sortable

    @property
    def expr(self) -> ColumnElement[Any]:
        return self.attribute.expression


@dataclass(frozen=True, slots=True)
class ModelMeta:
    model: type[Any]
    name: str
    mapper: Mapper[Any]
    fields: MappingProxyType[str, FieldMeta]
    pk: tuple[FieldMeta, ...]

    def field(self, name: str) -> FieldMeta:
        try:
            return self.fields[name]
        except KeyError:
            raise ConfigurationError(
                f"{self.model.__name__} has no column attribute {name!r}. "
                f"Available: {', '.join(sorted(self.fields))}"
            ) from None


def _python_type(t: types.TypeEngine[Any], kind: FieldKind) -> type | None:
    if kind in _PY_TYPES:
        return _PY_TYPES[kind]
    try:
        return t.python_type
    except NotImplementedError:
        return None


def _field(prop: ColumnProperty[Any], attribute: InstrumentedAttribute[Any]) -> FieldMeta | None:
    col = prop.columns[0]
    if not isinstance(col, Column):
        return None  # column_property() over an expression: handled as a computed field later
    field_type = default_field_type(col.type)
    kind = field_type.kind
    base = unwrap(col.type)
    enum_class: type[enum.Enum] | None = None
    enum_values: tuple[str, ...] | None = None
    if isinstance(base, types.Enum):
        enum_class = base.enum_class
        enum_values = tuple(base.enums)
    autoinc_pk = (
        col.primary_key
        and kind == "integer"
        and col.autoincrement in (True, "auto")
        and col.server_default is None
        and len(col.table.primary_key.columns) == 1
        and not col.foreign_keys
    )
    generated = isinstance(col.server_default, Computed | Identity) or autoinc_pk
    return FieldMeta(
        name=prop.key,
        attribute=attribute,
        column=col,
        field_type=field_type,
        python_type=_python_type(base, kind),
        nullable=bool(col.nullable) and not col.primary_key,
        primary_key=col.primary_key,
        max_length=getattr(base, "length", None) if kind == "string" else None,
        enum_class=enum_class,
        enum_values=enum_values,
        tz_aware=bool(getattr(base, "timezone", False)) if kind in ("datetime", "time") else False,
        has_default=col.default is not None or col.server_default is not None,
        generated=generated,
        auto_updated=col.onupdate is not None or col.server_onupdate is not None,
    )


def introspect(model: type[Any], *, name: str | None = None) -> ModelMeta:
    """Build ``ModelMeta`` for a mapped class. Raises ``ConfigurationError`` if not mapped."""
    try:
        mapper: Mapper[Any] = inspect(model)
    except Exception as exc:
        raise ConfigurationError(
            f"{model!r} is not a SQLAlchemy mapped class. Register declarative models only."
        ) from exc
    fields: dict[str, FieldMeta] = {}
    for prop in mapper.column_attrs:
        attribute = getattr(model, prop.key)
        meta = _field(prop, attribute)
        if meta is not None:
            fields[meta.name] = meta
    by_column: dict[Any, FieldMeta] = {f.column: f for f in fields.values()}
    pk = tuple(by_column[c] for c in mapper.primary_key if c in by_column)
    if len(pk) != len(mapper.primary_key):
        raise ConfigurationError(
            f"{model.__name__}: every primary key column must be mapped as a plain "
            "column attribute."
        )
    return ModelMeta(
        model=model,
        name=name or str(getattr(mapper.local_table, "name", model.__name__)),
        mapper=mapper,
        fields=MappingProxyType(fields),
        pk=pk,
    )
