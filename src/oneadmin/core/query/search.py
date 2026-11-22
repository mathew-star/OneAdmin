"""Django-style free-text search.

``search_fields`` entries are field names with an optional prefix:
- ``^name``: starts with (case-insensitive). Index-friendly with ``text_pattern_ops`` or
  a trigram index.
- ``=name``: exact match (case-insensitive for text, typed equality otherwise).
- ``name``: contains (case-insensitive). Needs a trigram index to be fast on big tables.

The term is split on whitespace. Every term must match at least one field
(AND of terms, OR of fields).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, false, func, or_
from sqlalchemy.sql.elements import ColumnElement

from oneadmin.core.coerce import parse_text
from oneadmin.core.errors import ConfigurationError, InvalidSearch
from oneadmin.core.meta import FieldMeta, ModelMeta

MAX_TERMS = 8
MAX_LENGTH = 200

Mode = Literal["startswith", "exact", "contains"]


@dataclass(frozen=True, slots=True)
class SearchField:
    field: FieldMeta
    mode: Mode


def compile_search_fields(meta: ModelMeta, spec: Sequence[str]) -> tuple[SearchField, ...]:
    """Validate ``ModelAdmin.search_fields`` at registration time."""
    out: list[SearchField] = []
    for raw in spec:
        mode: Mode = "contains"
        name = raw
        if raw[:1] == "^":
            mode, name = "startswith", raw[1:]
        elif raw[:1] == "=":
            mode, name = "exact", raw[1:]
        field = meta.field(name)
        if mode != "exact" and field.kind not in ("string", "text"):
            raise ConfigurationError(
                f"search_fields: {name!r} is {field.kind}; only text columns support "
                f"partial matching. Use '={name}' for exact matching."
            )
        out.append(SearchField(field, mode))
    return tuple(out)


def search_clause(fields: Sequence[SearchField], term: str) -> ColumnElement[bool] | None:
    term = term.strip()
    if not term or not fields:
        return None
    if len(term) > MAX_LENGTH:
        raise InvalidSearch(f"search is limited to {MAX_LENGTH} characters", param="q")
    words = term.split()
    if len(words) > MAX_TERMS:
        raise InvalidSearch(f"search is limited to {MAX_TERMS} words", param="q")
    per_word: list[ColumnElement[bool]] = []
    for word in words:
        options: list[ColumnElement[bool]] = []
        for sf in fields:
            e = sf.field.expr
            if sf.mode == "contains":
                options.append(e.icontains(word, autoescape=True))
            elif sf.mode == "startswith":
                options.append(e.istartswith(word, autoescape=True))
            elif sf.field.kind in ("string", "text"):
                options.append(func.lower(e) == word.lower())
            else:
                try:
                    options.append(e == parse_text(sf.field, word))
                except ValueError:
                    continue  # "abc" can't equal an integer id; that's not an error
        per_word.append(or_(*options) if options else false())
    return and_(*per_word)
