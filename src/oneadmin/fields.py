"""Field types: how OneAdmin parses, validates, filters and displays each kind of value.

Use them in ``ModelAdmin.field_types`` or ``conventions.field_type(...)``, and subclass
one to make your own. See ``oneadmin.core.fields`` for the protocol (ADR-0020).
"""

from oneadmin.core.fields import (
    ArrayField,
    BinaryField,
    BooleanField,
    DateField,
    DateTimeField,
    DecimalField,
    EmailField,
    EnumField,
    FieldType,
    FloatField,
    IntegerField,
    IntervalField,
    JSONField,
    MoneyField,
    StringField,
    TextField,
    TimeField,
    URLField,
    UUIDField,
)

__all__ = [
    "ArrayField",
    "BinaryField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "EmailField",
    "EnumField",
    "FieldType",
    "FloatField",
    "IntegerField",
    "IntervalField",
    "JSONField",
    "MoneyField",
    "StringField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
]
