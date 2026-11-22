"""``FieldType``: default resolution, the custom built-ins, and the extension contract."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import JSON, BigInteger, Enum, Numeric, String, Text, types

from oneadmin.core.fields import (
    DecimalField,
    EmailField,
    EnumField,
    FieldType,
    IntegerField,
    JSONField,
    MoneyField,
    StringField,
    TextField,
    UnknownField,
    URLField,
    default_field_type,
)
from oneadmin.core.meta import FieldMeta, introspect
from tests.models import Color, Item, Lowercase

ITEM = introspect(Item)


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        (String(10), StringField()),
        (Text(), TextField()),
        (BigInteger(), IntegerField()),
        (Numeric(10, 2), DecimalField()),
        (Enum(Color), EnumField()),
        (JSON(), JSONField()),
        (Lowercase(), StringField()),  # through a TypeDecorator
        (types.NullType(), UnknownField()),
    ],
)
def test_default_types_by_sql_type(sql_type: types.TypeEngine[Any], expected: FieldType) -> None:
    assert default_field_type(sql_type) == expected


def test_field_meta_exposes_kind_and_sortability_from_its_type() -> None:
    amount = ITEM.fields["amount"]
    assert (amount.kind, amount.sortable, amount.field_type) == ("decimal", True, DecimalField())


def with_type(name: str, field_type: FieldType) -> FieldMeta:
    return replace(ITEM.fields[name], field_type=field_type)


def test_email_field() -> None:
    f = with_type("name", EmailField())
    assert (f.kind, f.field_type.widget_key) == ("string", "email")
    assert f.field_type.parse_input(f, " a@b.co ") == "a@b.co"
    with pytest.raises(ValueError, match="must be an email address"):
        f.field_type.parse_input(f, "not-an-email")
    assert f.field_type.filter_ops == StringField.filter_ops, "inherits string filtering"


def test_url_field() -> None:
    f = with_type("name", URLField())
    assert f.field_type.parse_input(f, "https://example.com/x") == "https://example.com/x"
    for bad in ("javascript:alert(1)", "ftp://x.y", "example.com"):
        with pytest.raises(ValueError, match="http:// or https://"):
            f.field_type.parse_input(f, bad)


def test_money_field_keeps_decimal_rules_and_describes_its_currency() -> None:
    f = with_type("amount", MoneyField("EUR"))
    assert f.kind == "decimal"
    assert f.field_type.widget_key == "money"
    assert f.field_type.widget_options() == {"currency": "EUR"}
    assert f.field_type.parse_input(f, "12.50") == Decimal("12.50")
    with pytest.raises(ValueError, match="at most 2 decimal places"):
        f.field_type.parse_input(f, "1.001")
    assert repr(MoneyField("EUR")) == "MoneyField(currency='EUR')"
    assert MoneyField("EUR") == MoneyField("EUR") != MoneyField("USD")
    with pytest.raises(ValueError, match="ISO 4217"):
        MoneyField("euro")


def test_a_custom_type_is_one_class() -> None:
    class SlugField(StringField):
        widget = "slug"

        def parse_input(self, field: FieldMeta, raw: Any) -> Any:
            value = super().parse_input(field, raw)
            if not value.replace("-", "").isalnum() or value != value.lower():
                raise ValueError("only lowercase letters, digits and hyphens")
            return value

    f = with_type("name", SlugField())
    assert f.field_type.parse_input(f, "my-post") == "my-post"
    with pytest.raises(ValueError, match="lowercase"):
        f.field_type.parse_input(f, "My Post")
    assert f.field_type.parse_text(f, "my") == "my", "filtering is inherited"
    assert f.sortable


def test_read_only_kinds_refuse_input_and_filters() -> None:
    f = with_type("name", JSONField())
    assert not f.field_type.writable
    assert f.field_type.filter_ops == ()
    with pytest.raises(ValueError, match="can't be edited"):
        f.field_type.parse_input(f, {})
