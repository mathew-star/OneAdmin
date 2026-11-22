"""Site-wide configuration rules for ``AdminSite(conventions=[...])`` (ADR-0020).

See ``oneadmin.core.conventions`` for the full description, precedence and examples.
"""

from oneadmin.core.conventions import (
    ALL,
    Convention,
    field_type,
    filterable,
    hide,
    label,
    readonly,
    scope_by,
)

__all__ = [
    "ALL",
    "Convention",
    "field_type",
    "filterable",
    "hide",
    "label",
    "readonly",
    "scope_by",
]
