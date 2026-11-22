"""Validation of create/update payloads (ADR-0018).

Each ``ModelAdmin`` compiles a ``WriteSpec``: the fields a client may write and how to parse
them. Input uses the same JSON shapes the read API emits, so a value read from the API can
be sent back unchanged:

======================  =====================================================================
Kind                    Accepted JSON
======================  =====================================================================
string, text            string (``max_length`` enforced, no NUL characters)
integer                 integer, or a string of digits (values beyond ±2^53 are sent as
                        strings by the read API); range-checked for the column type
decimal                 string or integer (never a float: binary floats lose cents);
                        precision and scale enforced
float                   number
boolean                 ``true`` / ``false``
datetime                ISO 8601 string; an offset is required for tz-aware columns and
                        refused for naive ones
date / time             ISO 8601 string
interval                number of seconds
uuid                    string
enum                    a member's value or name
======================  =====================================================================

The table describes the built-in field types; parsing is done by each column's
``FieldType.parse_input``, so custom types (ADR-0020) define their own rules.

Rules:
- **Mass assignment:** a key that isn't a writable field is an error. Read-only, generated,
  auto-updated (``onupdate``), hidden and unknown keys are all refused, never silently dropped.
- **Omittable is not nullable:** on update, a missing key means "leave unchanged". ``null``
  is accepted only for nullable columns.
- **Create:** NOT NULL columns without a default must be present.
- **Blank text:** required text fields refuse ``""`` unless listed in ``blank_fields``.
- **Primary keys** can be set on create (natural keys) but never changed afterwards.
- Every field error is collected, so the client can show them all at once.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from oneadmin.core.errors import ValidationError
from oneadmin.core.fields import MAX_TEXT_INPUT
from oneadmin.core.meta import FieldMeta

__all__ = ["MAX_TEXT_INPUT", "WriteField", "WriteSpec", "parse_input"]


@dataclass(frozen=True, slots=True)
class WriteField:
    meta: FieldMeta
    required: bool
    """Must be present on create: NOT NULL, no default, not generated."""
    allow_blank: bool = True
    """For text: whether ``""`` (or only whitespace) is acceptable. Required text fields
    refuse it unless listed in ``ModelAdmin.blank_fields``: an empty title or slug is almost
    always a mistake, even though the database would store it."""


@dataclass(frozen=True, slots=True)
class WriteSpec:
    fields: Mapping[str, WriteField]
    """Writable fields, in model order."""
    readonly: frozenset[str]
    """Visible but not writable (for clearer error messages)."""

    @classmethod
    def build(
        cls,
        visible: Collection[FieldMeta],
        readonly: Collection[str],
        blank: Collection[str] = (),
    ) -> WriteSpec:
        writable: dict[str, WriteField] = {}
        blocked: set[str] = set(readonly)
        for f in visible:
            if f.name in blocked or f.generated or f.auto_updated or not f.field_type.writable:
                blocked.add(f.name)
                continue
            required = not f.nullable and not f.has_default
            writable[f.name] = WriteField(f, required, allow_blank=not required or f.name in blank)
        return cls(MappingProxyType(writable), frozenset(blocked))

    def parse(self, payload: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
        """Validate ``payload`` and return typed values. Raises ``ValidationError``."""
        errors: dict[str, str] = {}
        values: dict[str, Any] = {}
        for key, raw in payload.items():
            spec = self.fields.get(key)
            if spec is None:
                errors[key] = "is read-only" if key in self.readonly else "is not a writable field"
                continue
            if spec.meta.primary_key and not creating:
                errors[key] = "is the primary key and can't be changed"
                continue
            if raw is None:
                if spec.meta.nullable:
                    values[key] = None
                else:
                    errors[key] = "may not be empty"
                continue
            try:
                values[key] = parse_input(spec.meta, raw)
            except ValueError as exc:
                errors[key] = str(exc)
                continue
            if not spec.allow_blank and isinstance(values[key], str) and not values[key].strip():
                errors[key] = "may not be blank"
        if creating:
            for name, spec in self.fields.items():
                if spec.required and name not in payload:
                    errors[name] = "is required"
        if errors:
            raise ValidationError(errors)
        return values


def parse_input(field: FieldMeta, raw: Any) -> Any:
    """Parse one non-null JSON value for ``field`` with its ``FieldType``.

    Raises ``ValueError`` (client-safe message).
    """
    return field.field_type.parse_input(field, raw)
