"""Field types: everything OneAdmin knows about one kind of value, in one class (ADR-0020).

A ``FieldType`` decides, for the columns it is assigned to:

========================  ==================================================================
``kind``                  the semantic base the API and UI branch on (``"decimal"``, ...)
``widget``                the UI renderer key; unknown keys fall back to ``kind``
``widget_options()``      extra settings for the renderer (e.g. a currency)
``sortable``              usable as a keyset sort key
``writable``              editable through the admin
``filter_ops``            allowed list-filter operators
``to_wire``               database value -> JSON for the API
``parse_text``            query-string text -> value (filters, search, primary keys)
``parse_input``           JSON from a form -> value (create/update)
``to_cursor/from_cursor`` lossless JSON inside signed pagination cursors
========================  ==================================================================

Every column gets a type when its model is introspected: by SQLAlchemy type, then
overridden by site conventions and ``ModelAdmin.field_types``. Custom types subclass a
built-in and change what they need::

    class SlugField(StringField):
        widget = "slug"

        def parse_input(self, field, raw):
            value = super().parse_input(field, raw)
            if not SLUG.fullmatch(value):
                raise ValueError("only lowercase letters, digits and hyphens")
            return value

Instances must be immutable: one instance can serve many columns and sites. Every
``ValueError`` message is shown to the client, so keep them free of internal details.
"""

from __future__ import annotations

import enum
import math
import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from sqlalchemy import types

if TYPE_CHECKING:
    from oneadmin.core.meta import FieldMeta

FieldKind = Literal[
    "string",
    "text",
    "integer",
    "decimal",
    "float",
    "boolean",
    "datetime",
    "date",
    "time",
    "interval",
    "uuid",
    "enum",
    "json",
    "array",
    "binary",
    "unknown",
]

MAX_TEXT_LENGTH = 1_000
"""Longest accepted query-string value (filters, search words, primary keys)."""
MAX_TEXT_INPUT = 500_000
"""Longest accepted text input for columns without a length (bodies are capped at 2 MiB)."""
JS_SAFE_INT = 2**53 - 1

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})
_ORDERED = ("eq", "ne", "gt", "gte", "lt", "lte", "in")
_TEXT_OPS = ("eq", "ne", "in", "contains", "icontains", "startswith", "istartswith")
_INT_RANGES: tuple[tuple[type[types.TypeEngine[Any]], int], ...] = (
    (types.SmallInteger, 2**15),
    (types.BigInteger, 2**63),
    (types.Integer, 2**31),
)


class FieldType:
    """Base class. Subclass a concrete built-in (``StringField``, ``DecimalField``...)."""

    kind: ClassVar[FieldKind] = "unknown"
    widget: str = ""
    """UI renderer key. Empty means "the default for ``kind``"."""
    sortable: ClassVar[bool] = False
    writable: ClassVar[bool] = False
    filter_ops: ClassVar[tuple[str, ...]] = ()

    # ---- description ---------------------------------------------------------------------
    @property
    def widget_key(self) -> str:
        return self.widget or self.kind

    def widget_options(self) -> dict[str, Any] | None:
        """Settings sent to the UI renderer (must be JSON-safe)."""
        return None

    def describe(self) -> str:
        """A short, stable description for ``oneadmin explain`` and ``schema``."""
        options = self.widget_options()
        args = ", ".join(f"{k}={v!r}" for k, v in sorted((options or {}).items()))
        return f"{type(self).__name__}({args})"

    def __repr__(self) -> str:
        return self.describe()

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FieldType)
            and type(self) is type(other)
            and self.describe() == other.describe()
        )

    def __hash__(self) -> int:
        return hash(self.describe())

    # ---- conversions ---------------------------------------------------------------------
    def to_wire(self, value: Any) -> Any:
        return to_wire(value)

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        raise ValueError(f"filtering on {self.kind} columns is not supported")

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        raise ValueError("this field can't be edited")

    def to_cursor(self, value: Any) -> Any:
        return to_cursor_json(value)

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        raise ValueError(f"cursor value has the wrong type for {field.name}")


# ---- text ---------------------------------------------------------------------------------
class StringField(FieldType):
    # Annotated here so subclasses (TextField) may narrow them.
    kind: ClassVar[FieldKind] = "string"
    sortable = True
    writable = True
    filter_ops: ClassVar[tuple[str, ...]] = _TEXT_OPS

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        if field.max_length is not None and len(raw) > field.max_length:
            raise ValueError(f"longer than column length {field.max_length}")
        return raw

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if not isinstance(raw, str):
            raise ValueError("must be text")
        limit = field.max_length or MAX_TEXT_INPUT
        if len(raw) > limit:
            raise ValueError(f"must be at most {limit} characters")
        if "\x00" in raw:
            raise ValueError("must not contain NUL characters")
        return raw

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return raw
        return super().from_cursor(field, raw)


class TextField(StringField):
    kind = "text"
    filter_ops = ("contains", "icontains", "startswith", "istartswith", "eq")


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_URL = re.compile(r"https?://[^\s/$.?#][^\s]*", re.IGNORECASE)


class EmailField(StringField):
    """An email address: validated on input, shown as a ``mailto:`` link."""

    widget = "email"

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        value = super().parse_input(field, raw)
        if value and not _EMAIL.fullmatch(value.strip()):
            raise ValueError("must be an email address")
        return value.strip()


class URLField(StringField):
    """An ``http(s)`` URL: validated on input, shown as a link opening in a new tab."""

    widget = "url"

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        value = super().parse_input(field, raw)
        if value and not _URL.fullmatch(value.strip()):
            raise ValueError("must be an http:// or https:// URL")
        return value.strip()


# ---- numbers ------------------------------------------------------------------------------
class IntegerField(FieldType):
    kind = "integer"
    sortable = True
    writable = True
    filter_ops = _ORDERED

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        if not (raw.isascii() and raw.strip().lstrip("+-").isdigit()):
            raise ValueError("must be an integer")
        value = int(raw)
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError("integer out of range")
        return value

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool):
            raise ValueError("must be an integer")
        if isinstance(raw, str):  # the read API sends integers beyond 2^53 as strings
            text = raw.strip()
            if not (text.isascii() and text.lstrip("+-").isdigit() and len(text) <= 20):
                raise ValueError("must be an integer")
            raw = int(text)
        if not isinstance(raw, int):
            raise ValueError("must be an integer")
        bound = _int_bound(field)
        if not -bound <= raw < bound:
            raise ValueError("number out of range for this column")
        return raw

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        return super().from_cursor(field, raw)


class DecimalField(FieldType):
    kind = "decimal"
    sortable = True
    writable = True
    filter_ops = _ORDERED

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        try:
            dec = Decimal(raw)
        except (InvalidOperation, ArithmeticError):
            raise ValueError("must be a number") from None
        if not dec.is_finite():
            raise ValueError("must be a finite number")
        check_precision(field, dec)
        return dec

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise ValueError('must be a decimal number, sent as a string (e.g. "12.50")')
        try:
            dec = Decimal(raw.strip() if isinstance(raw, str) else raw)
        except InvalidOperation:
            raise ValueError("must be a decimal number") from None
        if not dec.is_finite():
            raise ValueError("must be a finite number")
        scale = getattr(field.column.type, "scale", None)
        if scale is not None:
            exponent = dec.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > scale:
                raise ValueError(f"must have at most {scale} decimal places")
        check_precision(field, dec)
        return dec

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return Decimal(raw)
        return super().from_cursor(field, raw)


class MoneyField(DecimalField):
    """A decimal amount shown with a currency (``MoneyField("EUR")``). Values stay exact."""

    widget = "money"

    def __init__(self, currency: str) -> None:
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be an ISO 4217 code such as 'EUR'")
        self.currency = currency

    def widget_options(self) -> dict[str, Any] | None:
        return {"currency": self.currency}


class FloatField(FieldType):
    kind = "float"
    sortable = True
    writable = True
    filter_ops = ("gt", "gte", "lt", "lte")

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("must be a number") from None
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("must be a number")
        try:
            value = float(raw)
        except OverflowError:
            raise ValueError("number out of range") from None
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    def to_cursor(self, value: Any) -> Any:
        return (
            {"f": repr(value)} if isinstance(value, float) and not math.isfinite(value) else value
        )

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
        if isinstance(raw, dict) and isinstance(raw.get("f"), str):
            return float(raw["f"])
        return super().from_cursor(field, raw)


# ---- booleans, dates and times ------------------------------------------------------------
class BooleanField(FieldType):
    kind = "boolean"
    sortable = True
    writable = True
    filter_ops = ("eq",)

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        low = raw.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError("must be true or false")

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if not isinstance(raw, bool):
            raise ValueError("must be true or false")
        return raw

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool):
            return raw
        return super().from_cursor(field, raw)


class DateTimeField(FieldType):
    kind = "datetime"
    sortable = True
    writable = True
    filter_ops = ("gt", "gte", "lt", "lte")

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        return parse_datetime(field, raw)

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        return parse_datetime(field, _iso(raw))

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        return super().from_cursor(field, raw)


class DateField(FieldType):
    kind = "date"
    sortable = True
    writable = True
    filter_ops = _ORDERED

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        return date.fromisoformat(raw)

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        return date.fromisoformat(_iso(raw))

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return date.fromisoformat(raw)
        return super().from_cursor(field, raw)


class TimeField(FieldType):
    kind = "time"
    sortable = True
    writable = True
    filter_ops = ("gt", "gte", "lt", "lte")

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        return time.fromisoformat(raw)

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        return time.fromisoformat(_iso(raw))

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return time.fromisoformat(raw)
        return super().from_cursor(field, raw)


class IntervalField(FieldType):
    """A duration; sent and accepted as a number of seconds."""

    kind = "interval"
    sortable = True
    writable = True

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError("must be a number of seconds")
        try:
            return timedelta(seconds=raw)
        except (OverflowError, ValueError):
            raise ValueError("duration out of range") from None

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, list) and len(raw) == 3 and all(isinstance(x, int) for x in raw):
            return timedelta(days=raw[0], seconds=raw[1], microseconds=raw[2])
        return super().from_cursor(field, raw)


# ---- identifiers and choices --------------------------------------------------------------
class UUIDField(FieldType):
    kind = "uuid"
    sortable = True
    writable = True
    filter_ops = ("eq", "ne", "in")

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        return uuid.UUID(raw)

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if not isinstance(raw, str):
            raise ValueError("must be a UUID string")
        try:
            return uuid.UUID(raw)
        except ValueError:
            raise ValueError("must be a UUID") from None

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            return uuid.UUID(raw)
        return super().from_cursor(field, raw)


class EnumField(FieldType):
    """A SQL ``Enum`` column; accepts a member's value or name."""

    kind = "enum"
    sortable = True
    writable = True
    filter_ops = ("eq", "ne", "in")

    def parse_text(self, field: FieldMeta, raw: str) -> Any:
        _check_text_length(raw)
        cls = field.enum_class
        if cls is None:
            if field.enum_values is not None and raw not in field.enum_values:
                raise ValueError(f"must be one of {', '.join(field.enum_values)}")
            return raw
        for member in cls:
            if raw in (member.name, str(member.value)):
                return member
        raise ValueError(f"must be one of {', '.join(str(m.value) for m in cls)}")

    def parse_input(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, bool) or not isinstance(raw, str | int | float):
            raise ValueError("must be one of the listed choices")
        cls = field.enum_class
        if cls is None:
            if not isinstance(raw, str) or (field.enum_values and raw not in field.enum_values):
                raise ValueError(f"must be one of {', '.join(field.enum_values or ())}")
            return raw
        for member in cls:  # the read API sends the value when JSON-safe, else the name
            if raw in (member.value, member.name):
                return member
        raise ValueError(f"must be one of {', '.join(str(m.value) for m in cls)}")

    def from_cursor(self, field: FieldMeta, raw: Any) -> Any:
        if isinstance(raw, str):
            if field.enum_class is not None:
                try:
                    return field.enum_class[raw]
                except KeyError:
                    raise ValueError(f"unknown enum member for {field.name}") from None
            return raw
        return super().from_cursor(field, raw)


# ---- read-only kinds (v1) -----------------------------------------------------------------
class JSONField(FieldType):
    kind = "json"


class ArrayField(FieldType):
    kind = "array"


class BinaryField(FieldType):
    """Binary data is never sent to clients (``to_wire`` returns ``None``)."""

    kind = "binary"

    def to_wire(self, value: Any) -> Any:
        return None


class UnknownField(FieldType):
    kind = "unknown"


# ---- defaults by SQLAlchemy type ----------------------------------------------------------
#: Checked in order: subclasses first (Enum < String, Text < String, Float < Numeric).
_BY_SQL_TYPE: tuple[tuple[type[types.TypeEngine[Any]], FieldType], ...] = (
    (types.Enum, EnumField()),
    (types.Boolean, BooleanField()),
    (types.Integer, IntegerField()),
    (types.Float, FloatField()),
    (types.Numeric, DecimalField()),
    (types.DateTime, DateTimeField()),
    (types.Date, DateField()),
    (types.Time, TimeField()),
    (types.Interval, IntervalField()),
    (types.Uuid, UUIDField()),
    (types.JSON, JSONField()),
    (types.ARRAY, ArrayField()),
    (types.LargeBinary, BinaryField()),
    (types._Binary, BinaryField()),
    (types.Text, TextField()),
    (types.String, StringField()),
)
_UNKNOWN = UnknownField()


def unwrap(t: types.TypeEngine[Any]) -> types.TypeEngine[Any]:
    """The underlying type of a ``TypeDecorator`` (up to 10 levels deep)."""
    seen = 0
    while isinstance(t, types.TypeDecorator) and seen < 10:
        t = t.impl_instance
        seen += 1
    return t


def default_field_type(sql_type: types.TypeEngine[Any]) -> FieldType:
    """The built-in type for a column's SQLAlchemy type."""
    base = unwrap(sql_type)
    for cls, field_type in _BY_SQL_TYPE:
        if isinstance(base, cls):
            return field_type
    return _UNKNOWN


# ---- shared helpers -----------------------------------------------------------------------
def to_wire(value: Any) -> Any:
    """Generic database value -> JSON-safe value (ADR-0008):

    decimals and integers beyond ±2^53 as strings, dates as ISO 8601, durations in seconds,
    enums by value (or name when the value isn't JSON-safe), binary as ``None``.
    """
    if value is None or isinstance(value, bool | str | float):
        return value
    if isinstance(value, int):
        return value if -JS_SAFE_INT <= value <= JS_SAFE_INT else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        v = value.value
        return v if isinstance(v, str | int | float | bool) else value.name
    if isinstance(value, bytes | bytearray | memoryview):
        return None
    if isinstance(value, dict):
        return {str(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_wire(v) for v in value]
    return str(value)


def to_cursor_json(value: Any) -> Any:
    """Lossless JSON for a sort-key value inside a cursor (decoded by ``from_cursor``)."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return {"f": repr(value)} if not math.isfinite(value) else value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return [value.days, value.seconds, value.microseconds]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.name
    raise TypeError(f"cannot encode sort value of type {type(value).__name__} in a cursor")


def parse_datetime(field: FieldMeta, raw: str) -> datetime:
    """ISO 8601, with an offset required for tz-aware columns and refused for naive ones."""
    value = datetime.fromisoformat(raw)
    if field.tz_aware and value.tzinfo is None:
        raise ValueError("timezone offset required (e.g. 2026-01-31T12:00:00Z)")
    if not field.tz_aware and value.tzinfo is not None:
        raise ValueError("this column stores naive datetimes; omit the timezone offset")
    return value


def check_precision(field: FieldMeta, dec: Decimal) -> None:
    """Refuse values that don't fit the column's ``NUMERIC(precision, scale)``."""
    precision = getattr(field.column.type, "precision", None)
    scale = getattr(field.column.type, "scale", None) or 0
    if precision is None:
        if abs(dec.adjusted()) > 1_000:
            raise ValueError("number out of range")
        return
    integer_digits = max(dec.adjusted() + 1, 0)
    if integer_digits > precision - scale:
        raise ValueError(f"number out of range for NUMERIC({precision},{scale})")


def _check_text_length(raw: str) -> None:
    if len(raw) > MAX_TEXT_LENGTH:
        raise ValueError(f"value longer than {MAX_TEXT_LENGTH} characters")


def _iso(raw: Any) -> str:
    if not isinstance(raw, str) or len(raw) > 64:
        raise ValueError("must be an ISO 8601 string")
    return raw


def _int_bound(field: FieldMeta) -> int:
    base = unwrap(field.column.type)
    for cls, bound in _INT_RANGES:
        if isinstance(base, cls):
            return bound
    return 2**63
