from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from oneadmin.core.coerce import from_json, parse_text, to_json
from oneadmin.core.errors import ConfigurationError
from oneadmin.core.meta import introspect
from tests.models import Color, Item, Pair

ITEM = introspect(Item)


def test_introspection_kinds_and_flags() -> None:
    f = ITEM.fields
    assert [p.name for p in ITEM.pk] == ["id"]
    assert f["id"].generated
    assert f["id"].primary_key
    assert not f["id"].nullable
    assert (f["grp"].kind, f["grp"].nullable) == ("integer", False)
    assert (f["seen_at"].kind, f["seen_at"].tz_aware, f["seen_at"].nullable) == (
        "datetime",
        True,
        True,
    )
    assert (f["name"].kind, f["name"].max_length) == ("string", 80)
    assert f["note"].kind == "text"
    assert (f["amount"].kind, f["amount"].python_type) == ("decimal", Decimal)
    assert f["color"].kind == "enum"
    assert f["color"].enum_class is Color
    assert f["slug"].kind == "string", "TypeDecorator is unwrapped to its impl"
    assert f["doubled"].generated, "Computed columns are never writable"


def test_composite_pk_order_is_mapper_order() -> None:
    meta = introspect(Pair)
    assert [p.name for p in meta.pk] == ["a", "b"]
    assert not meta.fields["a"].generated, "composite PK parts are client-supplied"


def test_unmapped_class_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="not a SQLAlchemy mapped class"):
        introspect(int)


def test_unknown_field_error_lists_alternatives() -> None:
    with pytest.raises(ConfigurationError, match="Available: amount, color"):
        ITEM.field("nope")


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("grp", "42", 42),
        ("grp", "-7", -7),
        ("amount", "10.50", Decimal("10.50")),
        ("seen_at", "2026-01-31T12:00:00+00:00", datetime(2026, 1, 31, 12, tzinfo=UTC)),
        ("color", "red", Color.RED),
        ("color", "GREEN", Color.GREEN),
        ("name", "Zoë ✓ 'quoted'; DROP TABLE x;--", "Zoë ✓ 'quoted'; DROP TABLE x;--"),
    ],
)
def test_parse_text_valid(field: str, raw: str, expected: Any) -> None:
    assert parse_text(ITEM.fields[field], raw) == expected


@pytest.mark.parametrize(
    ("field", "raw", "message"),
    [
        ("grp", "1.5", "integer"),
        ("grp", "١٢", "integer"),  # non-ASCII digits are rejected
        ("grp", str(2**64), "out of range"),
        ("amount", "NaN", "finite"),
        ("amount", "abc", "number"),
        ("seen_at", "2026-01-31T12:00:00", "timezone offset required"),
        ("color", "purple", "one of"),
        ("name", "x" * 81, "column length"),
        ("name", "x" * 5000, "longer than 1000"),
    ],
)
def test_parse_text_rejects(field: str, raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_text(ITEM.fields[field], raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grp", 3),
        ("amount", Decimal("12345678.91")),
        ("seen_at", datetime(2026, 5, 1, 1, 2, 3, 456789, tzinfo=UTC)),
        ("seen_at", None),
        ("color", Color.BLUE),
        ("name", "ünïcødé"),
    ],
)
def test_cursor_value_roundtrip(field: str, value: Any) -> None:
    f = ITEM.fields[field]
    assert from_json(f, to_json(value)) == value


def test_cursor_value_type_confusion_rejected() -> None:
    with pytest.raises(ValueError, match="wrong type"):
        from_json(ITEM.fields["grp"], "1")
    with pytest.raises(ValueError, match="wrong type"):
        from_json(ITEM.fields["grp"], True)
    with pytest.raises(ValueError, match="null value"):
        from_json(ITEM.fields["grp"], None)
    with pytest.raises(ValueError, match="unknown enum"):
        from_json(ITEM.fields["color"], "PURPLE")


def test_to_json_misc_types() -> None:
    assert to_json(timedelta(days=1, seconds=2)) == [1, 2, 0]
    assert to_json(date(2026, 1, 2)) == "2026-01-02"
    u = uuid.uuid4()
    assert to_json(u) == str(u)
    with pytest.raises(TypeError):
        to_json(object())
