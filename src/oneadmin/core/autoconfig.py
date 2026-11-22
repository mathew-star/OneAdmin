"""Suggested admin options for a model, from its columns alone (ROADMAP Phase 2).

One set of heuristics, used in two places so they always agree:
- ``AdminSite.register_all`` builds admins from the suggestions at startup.
- ``oneadmin init`` writes them out as an editable ``admin.py``.

The heuristics favour a useful *and fast* list page:
- **Columns:** the primary key, a label-like column, many-to-one relationships (shown by
  label) instead of raw foreign keys, then short columns, up to ``MAX_COLUMNS``.
- **Search:** only identifier-like text columns (name, title, email, ...); ``^`` (prefix)
  for codes and slugs, which an ordinary B-tree index can serve.
- **Filters:** booleans, enums and timestamps.
- **Ordering:** newest first, by ``created_at``-like timestamps when present, else the PK.

Everything here reads ``ModelMeta`` and mapper relationships, with no database access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import RelationshipDirection

from oneadmin.core.compiler import SENSITIVE
from oneadmin.core.meta import FieldMeta, ModelMeta, introspect

MAX_COLUMNS = 7
MAX_SEARCH = 3
MAX_FILTERS = 4

_LABEL_NAMES = ("name", "title", "username", "email", "label", "full_name", "slug", "code", "sku")
_SEARCH_CONTAINS = re.compile(
    r"(.*_)?(name|title|email|username|label)|first_name|last_name|full_name", re.IGNORECASE
)
_SEARCH_PREFIX = re.compile(r"(.*_)?(slug|code|sku|reference|ref|number)", re.IGNORECASE)
_CREATED = ("created_at", "created", "created_on", "inserted_at", "date_created", "timestamp")
_SHORT_KINDS = frozenset(
    {"string", "integer", "decimal", "float", "boolean", "datetime", "date", "uuid", "enum"}
)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Suggested ``ModelAdmin`` options, as attribute names (``"-x"`` = descending)."""

    model: type[Any]
    list_display: tuple[str, ...]
    search_fields: tuple[str, ...]
    list_filter: tuple[str, ...]
    ordering: tuple[str, ...]

    def as_options(self) -> dict[str, Any]:
        """Class attributes for a ``ModelAdmin`` subclass (empty options left out)."""
        options: dict[str, Any] = {"list_display": self.list_display, "ordering": self.ordering}
        if self.search_fields:
            options["search_fields"] = self.search_fields
        if self.list_filter:
            options["list_filter"] = self.list_filter
        return options


def suggest(model: type[Any]) -> Suggestion:
    meta = introspect(model)
    visible = [f for f in meta.fields.values() if not SENSITIVE.search(f.name)]
    return Suggestion(
        model=model,
        list_display=_columns(meta, visible),
        search_fields=_search(visible),
        list_filter=_filters(visible),
        ordering=_ordering(meta, visible),
    )


def _columns(meta: ModelMeta, visible: list[FieldMeta]) -> tuple[str, ...]:
    names: list[str] = [pk.name for pk in meta.pk]
    by_name = {f.name: f for f in visible}
    label = next((n for n in _LABEL_NAMES if n in by_name and by_name[n].kind == "string"), None)
    if label and label not in names:
        names.append(label)
    # Many-to-one relationships are shown by the related row's label; their raw FK
    # columns are left out.
    fk_columns: set[str] = set()
    for rel in meta.mapper.relationships:
        if rel.direction is not RelationshipDirection.MANYTOONE or len(rel.local_columns) != 1:
            continue
        local = next(iter(rel.local_columns))
        field = next((f for f in visible if f.column is local), None)
        if field is None:
            continue
        fk_columns.add(field.name)
        if len(names) < MAX_COLUMNS:
            names.append(rel.key)
    for f in visible:
        if len(names) >= MAX_COLUMNS:
            break
        if f.name in names or f.name in fk_columns or f.kind not in _SHORT_KINDS:
            continue
        if f.kind == "string" and (f.max_length is None or f.max_length > 255):
            continue  # long strings make lists unreadable; they belong to the detail view
        names.append(f.name)
    return tuple(names)


def _search(visible: list[FieldMeta]) -> tuple[str, ...]:
    out: list[str] = []
    for f in visible:
        if f.kind != "string" or len(out) >= MAX_SEARCH:
            continue
        if _SEARCH_PREFIX.fullmatch(f.name):
            out.append(f"^{f.name}")
        elif _SEARCH_CONTAINS.fullmatch(f.name):
            out.append(f.name)
    return tuple(out)


def _filters(visible: list[FieldMeta]) -> tuple[str, ...]:
    out = [f.name for f in visible if f.kind in ("boolean", "enum") and not f.primary_key]
    out += [f.name for f in visible if f.kind in ("datetime", "date") and not f.primary_key]
    return tuple(out[:MAX_FILTERS])


def _ordering(meta: ModelMeta, visible: list[FieldMeta]) -> tuple[str, ...]:
    by_name = {f.name: f for f in visible}
    for name in _CREATED:
        f = by_name.get(name)
        if f is not None and f.kind in ("datetime", "date") and not f.nullable:
            return (f"-{name}",)
    return tuple(f"-{pk.name}" for pk in meta.pk)
