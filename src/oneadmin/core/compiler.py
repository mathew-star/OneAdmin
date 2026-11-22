"""Compiling a ``ModelAdmin`` into an immutable ``CompiledAdmin`` (ADR-0020).

Configuration is resolved once, at startup, in ordered passes:

1. **introspection**: the model's columns, relationships and default field types
2. **conventions**: site-wide rules, in declaration order
3. **options**: the ``ModelAdmin``'s own attributes (they win)
4. **validation**: every mistake becomes a ``ConfigurationError`` naming the option

Every per-field decision records its ``Origin``, so ``oneadmin explain`` can say why a field
is read-only, hidden, or typed the way it is. Nothing here runs per request.

Options that name columns accept strings or mapped attributes (``Post.title``);
``ordering`` also accepts ``Post.created_at.desc()``. They are normalised to names first.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from sqlalchemy import false
from sqlalchemy.orm import QueryableAttribute, RelationshipDirection, RelationshipProperty
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import UnaryExpression

from oneadmin.core.actions import DELETE_SELECTED, ActionSpec, declared_actions
from oneadmin.core.conventions import (
    ALL,
    DEFAULT,
    Convention,
    FieldConvention,
    Origin,
    ScopeBy,
)
from oneadmin.core.errors import ConfigurationError
from oneadmin.core.fields import FieldType
from oneadmin.core.meta import FieldMeta, ModelMeta, introspect
from oneadmin.core.query.paginate import MAX_PAGE_SIZE
from oneadmin.core.query.search import SearchField, compile_search_fields
from oneadmin.core.query.sorting import validate_default_sort
from oneadmin.core.write_spec import WriteSpec

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    from oneadmin.core.context import AdminContext
    from oneadmin.core.model_admin import ModelAdmin

#: Columns whose names look like credentials are hidden unless listed in ``fields``.
SENSITIVE = re.compile(r"password|passwd|secret|token|api_key|_hash$|^hash$", re.IGNORECASE)
#: Column names tried, in order, to label a row of a model (e.g. in FK displays).
_LABEL_CANDIDATES = ("name", "title", "username", "email", "label", "slug", "code")
#: Kinds shown by default in lists; long text, JSON and binary are left to the detail view.
_DEFAULT_LIST_KINDS = frozenset(
    {"string", "integer", "decimal", "float", "boolean", "datetime", "date", "uuid", "enum"}
)
_DEFAULT_LIST_COLUMNS = 8
_SLUG = re.compile(r"[a-z0-9_\-]{1,64}")
_ACTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


# ---- compiled state -----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RelationSpec:
    """A many-to-one relationship rendered as ``{"pk": ..., "label": ...}``."""

    name: str
    local: FieldMeta
    """The foreign-key column on this model."""
    target: type[Any]
    remote_column: Any
    """The referenced column on the target model (usually its PK)."""


@dataclass(frozen=True, slots=True)
class CompiledScope:
    """A ``scope_by`` convention bound to this model's column."""

    rule: ScopeBy
    field: FieldMeta

    async def clause(self, ctx: AdminContext) -> ColumnElement[bool] | None:
        """The ``WHERE`` clause for ``ctx``, or ``None`` for "no restriction"."""
        value = await self.rule.resolve(ctx)
        if value is ALL:
            return None
        if value is None:
            return false()  # fail closed: no scope value means no rows
        if isinstance(value, Iterable) and not isinstance(value, str | bytes):
            return self.field.expr.in_(list(value))
        out: ColumnElement[bool] = self.field.expr == value
        return out


@dataclass(frozen=True, slots=True)
class CompiledAdmin:
    """Validated, immutable configuration of one ``ModelAdmin`` (internal API)."""

    model: type[Any]
    admin_class: type[Any]
    meta: ModelMeta
    """The model's metadata with this admin's field types applied."""
    slug: str
    detail_fields: tuple[FieldMeta, ...]
    list_columns: tuple[FieldMeta, ...]
    """Always starts with the primary key column(s)."""
    list_relations: tuple[RelationSpec, ...]
    list_display: tuple[str, ...]
    """Column and relation names in display order: ``list_display`` as written, with the
    primary key prepended when it isn't listed."""
    detail_relations: tuple[RelationSpec, ...]
    default_sort: tuple[str, ...]
    sort_allowed: frozenset[str]
    filter_allowed: frozenset[str]
    filter_fields: tuple[str, ...]
    search: tuple[SearchField, ...]
    label: FieldMeta
    write: WriteSpec
    """Which fields clients may write, and how their input is parsed (ADR-0018)."""
    actions: Mapping[str, ActionSpec]
    """Bulk actions by name, in declaration order (``delete_selected`` first if enabled)."""
    labels: Mapping[str, str]
    """Display label of every field and relation."""
    scopes: tuple[CompiledScope, ...]
    """``scope_by`` conventions that apply to this model (``ModelAdmin.apply_scope``)."""
    provenance: Mapping[str, Origin]
    """Why each setting has its value: ``"field.<name>.<setting>"`` or ``"<option>"``."""


# ---- the compiler -------------------------------------------------------------------------
class Compiler:
    """Turns options and conventions into a ``CompiledAdmin``, one pass per method."""

    def __init__(
        self, admin: ModelAdmin[Any], model: type[Any], conventions: Sequence[Convention] = ()
    ) -> None:
        self.admin = admin
        self.model = model
        self.owner = type(admin).__name__
        self.base_meta = introspect(model)
        self.meta = self.base_meta
        self.relationships: dict[str, RelationshipProperty[Any]] = {
            r.key: r for r in self.base_meta.mapper.relationships
        }
        self.provenance: dict[str, Origin] = {}
        self.conventions = self._active_conventions(conventions)

    def error(self, option: str, message: str) -> ConfigurationError:
        return ConfigurationError(f"{self.owner}.{option}: {message}")

    def option(self, name: str) -> Origin:
        return Origin("option", f"{self.owner}.{name}")

    # ---- entry point ---------------------------------------------------------------------
    def run(self) -> CompiledAdmin:
        admin = self.admin
        slug = self._slug()
        self.meta = self._apply_field_types()
        for option in ("exclude", "list_filter", "readonly_fields", "blank_fields"):
            for name in self.names(option):
                self.meta.field(name)  # raises with the list of valid names
        visible = self._visible_fields()
        visible_names = frozenset(f.name for f in visible)
        list_columns, list_relations, list_display = self._list_display(visible, visible_names)
        default_sort = self._default_sort()
        if not 1 <= admin.list_per_page <= MAX_PAGE_SIZE:
            raise self.error("list_per_page", f"must be between 1 and {MAX_PAGE_SIZE}")
        filters = self._filters(visible, visible_names)
        detail_relations = self._detail_relations(visible_names)
        return CompiledAdmin(
            model=self.model,
            admin_class=type(admin),
            meta=self.meta,
            slug=slug,
            detail_fields=visible,
            list_columns=list_columns,
            list_relations=list_relations,
            list_display=list_display,
            detail_relations=detail_relations,
            default_sort=default_sort,
            sort_allowed=self._sortable(list_columns, default_sort),
            filter_allowed=frozenset(filters),
            filter_fields=tuple(filters),
            search=self._search(visible_names),
            label=self._label(visible),
            write=self._write_spec(visible, visible_names),
            actions=self._actions(),
            labels=self._labels(visible, (*list_relations, *detail_relations)),
            scopes=self._scopes(),
            provenance=MappingProxyType(dict(self.provenance)),
        )

    # ---- option normalisation ------------------------------------------------------------
    def names(self, option: str, *, allow_desc: bool = False) -> list[str]:
        """The option's entries as attribute names (``"-name"`` for descending order)."""
        value = getattr(self.admin, option)
        if value is None:
            return []
        if isinstance(value, str | QueryableAttribute | UnaryExpression):
            raise self.error(option, "must be a sequence, e.g. a tuple; did you forget a comma?")
        return [self.ref(option, item, allow_desc=allow_desc) for item in value]

    def ref(self, option: str, item: Any, *, allow_desc: bool = False) -> str:
        """Normalise one reference: a name, ``Model.attr``, or ``Model.attr.desc()``."""
        if isinstance(item, str):
            return item
        if isinstance(item, QueryableAttribute):
            owner = item.class_
            if not (isinstance(owner, type) and issubclass(self.model, owner)):
                raise self.error(
                    option,
                    f"{owner.__name__}.{item.key} belongs to another model, not "
                    f"{self.model.__name__}",
                )
            return item.key
        if allow_desc and isinstance(item, UnaryExpression):
            descending = item.modifier is operators.desc_op
            if not descending and item.modifier is not operators.asc_op:
                raise self.error(option, f"unsupported ordering expression {item!r}")
            for f in self.base_meta.fields.values():
                if f.expr.compare(item.element):
                    return f"-{f.name}" if descending else f.name
            raise self.error(option, f"{item!r} isn't a column of {self.model.__name__}")
        kind = "a name, a mapped attribute" + (" or attr.desc()" if allow_desc else "")
        raise self.error(option, f"entries must be {kind}; got {item!r}")

    def _active_conventions(self, conventions: Sequence[Convention]) -> list[Convention]:
        ignored = set(self.names("ignore_conventions"))
        unknown = ignored - {c.id for c in conventions}
        if unknown:
            known = ", ".join(sorted(c.id for c in conventions)) or "none"
            raise self.error(
                "ignore_conventions", f"no convention with id {sorted(unknown)} (known: {known})"
            )
        return [c for c in conventions if c.id not in ignored]

    def _field_rules(self, action: str, f: FieldMeta) -> list[FieldConvention]:
        return [
            c
            for c in self.conventions
            if isinstance(c, FieldConvention) and c.action == action and c.matches(self.model, f)
        ]

    # ---- passes --------------------------------------------------------------------------
    def _apply_field_types(self) -> ModelMeta:
        """Default type -> conventions -> ``ModelAdmin.field_types``."""
        explicit: Mapping[Any, FieldType] = self.admin.field_types
        by_name: dict[str, FieldType] = {}
        for key, value in explicit.items():
            name = self.ref("field_types", key)
            self.base_meta.field(name)
            if not isinstance(value, FieldType):
                raise self.error("field_types", f"{name!r}: expected a FieldType, got {value!r}")
            by_name[name] = value
        fields: dict[str, FieldMeta] = {}
        for f in self.base_meta.fields.values():
            chosen, origin = f.field_type, Origin("default", "from the column's SQL type")
            for rule in self._field_rules("field_type", f):
                chosen, origin = rule.value, rule.origin
            if f.name in by_name:
                chosen, origin = by_name[f.name], self.option("field_types")
            if chosen.kind != f.field_type.kind and not _compatible(f.field_type, chosen):
                raise self.error(
                    "field_types",
                    f"{f.name!r} is a {f.kind} column; {chosen.describe()} handles {chosen.kind}",
                )
            fields[f.name] = f if chosen is f.field_type else replace(f, field_type=chosen)
            self.provenance[f"field.{f.name}.type"] = origin
        return replace(
            self.base_meta,
            fields=MappingProxyType(fields),
            pk=tuple(fields[p.name] for p in self.base_meta.pk),
        )

    def _visible_fields(self) -> tuple[FieldMeta, ...]:
        """Default (credential-like names hidden) -> ``hide`` conventions -> ``exclude`` /
        ``fields`` options. An explicit ``fields`` list wins over everything but ``exclude``."""
        excluded = set(self.names("exclude"))
        explicit = self.names("fields") if self.admin.fields is not None else None
        visible: list[FieldMeta] = []
        for f in self.meta.fields.values():
            key = f"field.{f.name}.visible"
            shown, origin = True, DEFAULT
            if SENSITIVE.search(f.name):
                shown, origin = False, Origin("default", "credential-like name")
            for rule in self._field_rules("hide", f):
                shown, origin = False, rule.origin
            if explicit is not None:
                shown, origin = f.name in explicit, self.option("fields")
            if f.name in excluded:
                shown, origin = False, self.option("exclude")
            self.provenance[key] = origin
            if shown:
                visible.append(f)
        if explicit is not None:  # keep the order the developer wrote
            order = {name: i for i, name in enumerate(explicit)}
            visible.sort(key=lambda f: order.get(f.name, len(order)))
        names = {f.name for f in visible}
        for pk in self.meta.pk:
            if pk.name not in names:
                origin = self.provenance[f"field.{pk.name}.visible"]
                raise self.error(
                    "exclude", f"the primary key {pk.name!r} cannot be hidden ({origin})"
                )
        return tuple(visible)

    def _write_spec(
        self, visible: tuple[FieldMeta, ...], visible_names: frozenset[str]
    ) -> WriteSpec:
        """Model-derived read-only -> ``readonly`` conventions -> ``readonly_fields``."""
        option_readonly = self.names("readonly_fields")
        for name in option_readonly:
            if name not in visible_names:
                raise self.error("readonly_fields", f"{name!r} is hidden, so it is never writable")
        blank = self.names("blank_fields")
        for name in blank:
            if self.meta.field(name).kind not in ("string", "text"):
                raise self.error("blank_fields", f"{name!r} is not a text column")
        readonly: set[str] = set()
        for f in visible:
            origin: Origin | None = _model_readonly(f)
            for rule in self._field_rules("readonly", f):
                origin = origin or rule.origin
            if f.name in option_readonly and origin is None:
                origin = self.option("readonly_fields")
            if origin is not None:
                readonly.add(f.name)
            self.provenance[f"field.{f.name}.readonly"] = origin or DEFAULT
        return WriteSpec.build(visible, readonly, blank)

    def _labels(
        self, visible: tuple[FieldMeta, ...], relations: Iterable[RelationSpec]
    ) -> Mapping[str, str]:
        """Default (the name in words) -> ``label`` conventions -> ``ModelAdmin.labels``."""
        explicit = {self.ref("labels", k): v for k, v in self.admin.labels.items()}
        known = {f.name for f in self.meta.fields.values()} | set(self.relationships)
        for name in explicit:
            if name not in known:
                raise self.error("labels", f"{name!r} is neither a column nor a relationship")
        labels: dict[str, str] = {}
        for f in visible:
            text, origin = humanize(f.name), DEFAULT
            for rule in self._field_rules("label", f):
                text, origin = rule.value, rule.origin
            if f.name in explicit:
                text, origin = explicit[f.name], self.option("labels")
            labels[f.name] = text
            self.provenance[f"field.{f.name}.label"] = origin
        for rel in relations:
            labels[rel.name] = explicit.get(rel.name, humanize(rel.name))
        return MappingProxyType(labels)

    def _scopes(self) -> tuple[CompiledScope, ...]:
        scopes: list[CompiledScope] = []
        for c in self.conventions:
            if isinstance(c, ScopeBy) and c.column in self.meta.fields:
                scopes.append(CompiledScope(c, self.meta.fields[c.column]))
                self.provenance[f"scope.{c.column}"] = c.origin
        return tuple(scopes)

    def _actions(self) -> Mapping[str, ActionSpec]:
        actions: dict[str, ActionSpec] = {}
        if self.admin.bulk_delete:
            actions[DELETE_SELECTED] = ActionSpec(
                name=DELETE_SELECTED,
                label="Delete selected",
                confirm="Delete the selected rows? This can't be undone.",
                permission="delete",
                destructive=True,
                method=None,
            )
        for name, options in declared_actions(type(self.admin)).items():
            if name == DELETE_SELECTED:
                raise self.error(name, "this name is reserved for the built-in bulk delete")
            if not _ACTION_NAME.fullmatch(name):
                raise self.error(name, "action names must be identifiers of at most 64 characters")
            actions[name] = ActionSpec(
                name=name,
                label=options.label or name.replace("_", " ").capitalize(),
                confirm=options.confirm,
                permission=options.permission,
                destructive=options.destructive,
                method=name,
            )
        return MappingProxyType(actions)

    def _slug(self) -> str:
        slug = self.admin.name or self.meta.name
        if not _SLUG.fullmatch(slug):
            raise self.error(
                "name", f"slug {slug!r} must be 1-64 characters of a-z, 0-9, '_' or '-'"
            )
        return slug

    def _list_display(
        self, visible: tuple[FieldMeta, ...], visible_names: frozenset[str]
    ) -> tuple[tuple[FieldMeta, ...], tuple[RelationSpec, ...], tuple[str, ...]]:
        if self.admin.list_display is None:
            names = [f.name for f in visible if f.kind in _DEFAULT_LIST_KINDS]
            names = names[:_DEFAULT_LIST_COLUMNS]
            self.provenance["list_display"] = Origin("default", "first short columns")
        else:
            names = self.names("list_display")
            self.provenance["list_display"] = self.option("list_display")
        columns: list[FieldMeta] = []
        relations: list[RelationSpec] = []
        for name in names:
            if name in visible_names:
                columns.append(self.meta.fields[name])
            elif name in self.relationships:
                rel = self.relationships[name]
                problem = self._relation_problem(rel, visible_names)
                if problem:
                    raise self.error("list_display", f"{name!r}: {problem}")
                relations.append(self._relation_spec(rel))
            elif name in self.meta.fields:
                origin = self.provenance[f"field.{name}.visible"]
                raise self.error("list_display", f"{name!r} is hidden ({origin})")
            else:
                raise self.error(
                    "list_display",
                    f"{name!r} is neither a column nor a relationship of {self.model.__name__}",
                )
        pk_first = [pk for pk in self.meta.pk if pk not in columns]
        order = tuple([pk.name for pk in pk_first] + list(names))
        return tuple(pk_first + columns), tuple(relations), order

    def _detail_relations(self, visible_names: frozenset[str]) -> tuple[RelationSpec, ...]:
        """Every displayable many-to-one relationship; others are silently skipped."""
        return tuple(
            self._relation_spec(rel)
            for rel in self.relationships.values()
            if self._relation_problem(rel, visible_names) is None
        )

    def _relation_problem(
        self, rel: RelationshipProperty[Any], visible_names: frozenset[str]
    ) -> str | None:
        if rel.direction is not RelationshipDirection.MANYTOONE:
            return "only many-to-one relationships can be displayed (v1)"
        if len(rel.local_columns) != 1:
            return "relationships over composite foreign keys can't be displayed (v1)"
        local = self._local_field(rel)
        if local is None or local.name not in visible_names:
            return "its foreign-key column is hidden or not mapped"
        return None

    def _local_field(self, rel: RelationshipProperty[Any]) -> FieldMeta | None:
        column = next(iter(rel.local_columns))
        return next((f for f in self.meta.fields.values() if f.column is column), None)

    def _relation_spec(self, rel: RelationshipProperty[Any]) -> RelationSpec:
        local = self._local_field(rel)
        if local is None:  # pragma: no cover - callers check _relation_problem first
            raise self.error("list_display", f"{rel.key!r}: cannot resolve its foreign key")
        remote = next(r for lc, r in rel.local_remote_pairs if lc is local.column)
        return RelationSpec(rel.key, local, rel.mapper.class_, remote)

    def _filters(self, visible: tuple[FieldMeta, ...], visible_names: frozenset[str]) -> list[str]:
        """``list_filter`` (explicit, validated) plus ``filterable`` conventions (lenient)."""
        names: list[str] = []
        for name in self.names("list_filter"):
            field = self.meta.fields[name]
            if name not in visible_names:
                raise self.error("list_filter", f"{name!r} is hidden")
            if not field.field_type.filter_ops:
                raise self.error(
                    "list_filter",
                    f"{field.kind} column {name!r} can't be filtered "
                    f"({field.field_type.describe()} allows no filter operators)",
                )
            names.append(name)
            self.provenance[f"field.{name}.filterable"] = self.option("list_filter")
        for f in visible:
            if f.name in names or not f.field_type.filter_ops:
                continue
            rules = self._field_rules("filterable", f)
            if rules:
                names.append(f.name)
                self.provenance[f"field.{f.name}.filterable"] = rules[-1].origin
        return names

    def _search(self, visible_names: frozenset[str]) -> tuple[SearchField, ...]:
        entries = [
            item if isinstance(item, str) else self.ref("search_fields", item)
            for item in self.admin.search_fields
        ]
        fields = compile_search_fields(self.meta, entries)
        for sf in fields:
            if sf.field.name not in visible_names:
                raise self.error("search_fields", f"{sf.field.name!r} is hidden")
        if entries:
            self.provenance["search_fields"] = self.option("search_fields")
        return fields

    def _default_sort(self) -> tuple[str, ...]:
        order = tuple(self.names("ordering", allow_desc=True))
        if order:
            self.provenance["ordering"] = self.option("ordering")
        else:
            order = tuple(f"-{pk.name}" for pk in self.meta.pk)
            self.provenance["ordering"] = Origin("default", "newest primary key first")
        for token in order:
            self.meta.field(token.lstrip("-"))
        validate_default_sort(self.meta, order)
        return order

    def _sortable(
        self, list_columns: tuple[FieldMeta, ...], default_sort: tuple[str, ...]
    ) -> frozenset[str]:
        if self.admin.sortable_fields is not None:
            names = {self.meta.field(n).name for n in self.names("sortable_fields")}
        else:
            names = {f.name for f in list_columns if f.sortable}
        names |= {token.lstrip("-") for token in default_sort}
        names |= {pk.name for pk in self.meta.pk}
        return frozenset(names)

    def _label(self, visible: tuple[FieldMeta, ...]) -> FieldMeta:
        if self.admin.label_field is not None:
            field = self.meta.field(self.ref("label_field", self.admin.label_field))
            if field not in visible:
                raise self.error("label_field", f"{field.name!r} is hidden")
            self.provenance["label_field"] = self.option("label_field")
            return field
        by_name = {f.name: f for f in visible}
        for candidate in _LABEL_CANDIDATES:
            match = by_name.get(candidate)
            if match is not None and match.kind in ("string", "text"):
                self.provenance["label_field"] = Origin(
                    "default", f"first of: {', '.join(_LABEL_CANDIDATES)}"
                )
                return match
        self.provenance["label_field"] = Origin("default", "no name-like column; the primary key")
        return self.meta.pk[0]


# ---- helpers ------------------------------------------------------------------------------
def _model_readonly(f: FieldMeta) -> Origin | None:
    """Read-only for reasons the model itself dictates (no option can make it writable)."""
    if f.generated:
        return Origin("model", "generated by the database")
    if f.auto_updated:
        return Origin("model", "set by onupdate on every update")
    if not f.field_type.writable:
        return Origin("model", f"{f.field_type.describe()} is not editable")
    return None


def _compatible(original: FieldType, chosen: FieldType) -> bool:
    """A type may replace another of a different kind only between text kinds."""
    return {original.kind, chosen.kind} <= {"string", "text"}


def humanize(name: str) -> str:
    """``created_at`` -> ``Created at``."""
    return name.replace("_", " ").strip().capitalize()
