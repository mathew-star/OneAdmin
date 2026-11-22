"""Input validation for writes (ADR-0018): every rule of ``WriteSpec`` without a database."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from oneadmin.core.errors import ValidationError
from oneadmin.core.fields import BooleanField, DateField, IntervalField, JSONField, UUIDField
from oneadmin.core.meta import introspect
from oneadmin.core.write_spec import WriteSpec, parse_input
from tests.models import Color, Item, Pair

ITEM = introspect(Item)
SPEC = WriteSpec.build(tuple(ITEM.fields.values()), readonly=("tenant",))
PAIR = WriteSpec.build(tuple(introspect(Pair).fields.values()), readonly=())


def errors(spec: WriteSpec, payload: dict[str, Any], *, creating: bool) -> dict[str, str]:
    with pytest.raises(ValidationError) as info:
        spec.parse(payload, creating=creating)
    return info.value.errors


def test_writable_fields_exclude_generated_and_readonly() -> None:
    assert set(SPEC.fields) == {"grp", "seen_at", "name", "note", "amount", "color", "slug"}
    assert {"id", "doubled", "tenant"} <= SPEC.readonly


def test_create_requires_not_null_columns_without_defaults() -> None:
    assert errors(SPEC, {}, creating=True) == {
        "grp": "is required",
        "name": "is required",
        "amount": "is required",
        "color": "is required",
    }


def test_update_accepts_a_partial_payload() -> None:
    assert SPEC.parse({"name": "x"}, creating=False) == {"name": "x"}
    assert SPEC.parse({}, creating=False) == {}


def test_null_only_for_nullable_columns() -> None:
    assert SPEC.parse({"note": None}, creating=False) == {"note": None}
    assert errors(SPEC, {"name": None}, creating=False) == {"name": "may not be empty"}


def test_natural_primary_keys_are_set_on_create_but_never_changed() -> None:
    assert PAIR.parse({"a": 1, "b": "x", "v": 2}, creating=True) == {"a": 1, "b": "x", "v": 2}
    assert errors(PAIR, {"a": 2}, creating=False) == {
        "a": "is the primary key and can't be changed"
    }


def test_unknown_and_readonly_keys_are_errors() -> None:
    assert errors(SPEC, {"tenant": 1, "doubled": 2, "zzz": 3}, creating=False) == {
        "tenant": "is read-only",
        "doubled": "is read-only",
        "zzz": "is not a writable field",
    }


F = ITEM.fields


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("grp", 5, 5),
        ("grp", "5", 5),  # big integers arrive as strings from the read API
        ("amount", "12.50", Decimal("12.50")),
        ("amount", 12, Decimal(12)),
        ("color", "red", Color.RED),
        ("color", "GREEN", Color.GREEN),  # member name also accepted
        ("seen_at", "2026-01-01T00:00:00+02:00", datetime(2025, 12, 31, 22, tzinfo=UTC)),
        ("name", "ünïcode ✓", "ünïcode ✓"),
    ],
)
def test_accepted_values(field: str, raw: Any, expected: Any) -> None:
    assert parse_input(F[field], raw) == expected


@pytest.mark.parametrize(
    ("field", "raw", "message"),
    [
        ("grp", True, "must be an integer"),
        ("grp", 1.5, "must be an integer"),
        ("grp", "1e3", "must be an integer"),
        ("grp", "١٢", "must be an integer"),  # non-ASCII digits
        ("grp", 2**31, "number out of range for this column"),
        ("amount", 1.5, 'must be a decimal number, sent as a string (e.g. "12.50")'),
        ("amount", "NaN", "must be a finite number"),
        ("amount", "abc", "must be a decimal number"),
        ("amount", "1.001", "must have at most 2 decimal places"),
        ("amount", "123456789.00", "number out of range for NUMERIC(10,2)"),
        ("color", "purple", "must be one of red, green, blue"),
        ("color", True, "must be one of the listed choices"),
        ("seen_at", "2026-01-01T00:00:00", "timezone offset required (e.g. 2026-01-31T12:00:00Z)"),
        ("seen_at", "yesterday", "Invalid isoformat string: 'yesterday'"),
        ("seen_at", 1700000000, "must be an ISO 8601 string"),
        ("name", "x" * 81, "must be at most 80 characters"),
        ("name", "a\x00b", "must not contain NUL characters"),
        ("name", 5, "must be text"),
        ("slug", "x" * 51, "must be at most 50 characters"),  # length through a TypeDecorator
    ],
)
def test_rejected_values(field: str, raw: Any, message: str) -> None:
    with pytest.raises(ValueError) as info:  # noqa: PT011 - the message is asserted below
        parse_input(F[field], raw)
    assert str(info.value) == message


def test_other_kinds() -> None:
    as_uuid = replace(F["name"], field_type=UUIDField())
    value = uuid.uuid4()
    assert parse_input(as_uuid, str(value)) == value
    with pytest.raises(ValueError, match="must be a UUID"):
        parse_input(as_uuid, "nope")
    as_interval = replace(F["grp"], field_type=IntervalField())
    assert parse_input(as_interval, 90.5) == timedelta(seconds=90.5)
    as_date = replace(F["name"], field_type=DateField())
    assert parse_input(as_date, "2026-02-28") == date(2026, 2, 28)
    as_bool = replace(F["grp"], field_type=BooleanField())
    with pytest.raises(ValueError, match="must be true or false"):
        parse_input(as_bool, "true")
    as_json = replace(F["note"], field_type=JSONField())
    with pytest.raises(ValueError, match="can't be edited"):
        parse_input(as_json, {})


class _Base(DeclarativeBase):
    pass


class _Article(_Base):
    __tablename__ = "ws_article"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def test_onupdate_columns_are_read_only_but_defaulted_ones_are_writable() -> None:
    spec = WriteSpec.build(tuple(introspect(_Article).fields.values()), readonly=())
    assert set(spec.fields) == {"created_at"}
    assert not spec.fields["created_at"].required, "a server default makes it optional"
    assert spec.readonly == {"id", "updated_at"}


def test_required_text_refuses_blank_unless_allowed() -> None:
    assert errors(SPEC, {"name": "  "}, creating=False) == {"name": "may not be blank"}
    assert SPEC.parse({"note": ""}, creating=False) == {"note": ""}, "optional text may be blank"
    lenient = WriteSpec.build(tuple(ITEM.fields.values()), readonly=(), blank=("name",))
    assert lenient.parse({"name": ""}, creating=False) == {"name": ""}
