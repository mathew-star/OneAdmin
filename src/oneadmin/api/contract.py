"""The ``/api/v1`` contract (ADR-0008). Pydantic models here are the single source of truth.

Bump ``CONTRACT_VERSION`` on any breaking change; additive changes keep it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from oneadmin.core.actions import MAX_ACTION_ROWS
from oneadmin.core.context import AdminContext
from oneadmin.core.fields import FieldKind
from oneadmin.core.meta import FieldMeta
from oneadmin.core.model_admin import CompiledAdmin, ModelAdmin
from oneadmin.core.query.counting import CountMethod

CONTRACT_VERSION = 1


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldSchema(_Out):
    name: str
    label: str
    kind: FieldKind
    """The semantic base the UI branches on when it doesn't know ``widget``."""
    widget: str
    """UI renderer key from the field type (``"email"``, ``"money"``...); defaults to ``kind``."""
    widget_options: dict[str, Any] | None = None
    nullable: bool
    primary_key: bool
    sortable: bool
    filter_ops: list[str]
    enum_values: list[str] | None = None
    max_length: int | None = None
    tz_aware: bool = False
    writable: bool = False
    """Clients may set it (on create; on update too unless it is the primary key)."""
    required: bool = False
    """Must be present on create (NOT NULL, no default)."""


class RelationSchema(_Out):
    name: str
    label: str
    local_field: str
    target: str | None
    """Slug of the target model's admin, or ``None`` if the target isn't registered."""


class ModelPermissions(_Out):
    """What the current user may do with this model (ADR-0019)."""

    view: bool
    add: bool
    change: bool
    delete: bool


class ActionSchema(_Out):
    name: str
    label: str
    confirm: str | None
    """Ask this question before running, if set."""
    destructive: bool


class ModelSchema(_Out):
    slug: str
    name: str
    name_plural: str
    pk: list[str]
    label_field: str
    fields: list[FieldSchema]
    relations: list[RelationSchema]
    list_display: list[str]
    list_filter: list[str]
    searchable: bool
    default_sort: list[str]
    per_page: int
    permissions: ModelPermissions
    actions: list[ActionSchema]
    """Actions the current user may run (each row is checked again when it runs)."""


class SiteSchema(_Out):
    contract_version: int
    title: str
    models: list[ModelSchema]


class RowOut(_Out):
    pk: str
    values: dict[str, Any]
    version: str | None = None
    """Detail reads only: send it back in ``If-Match`` to update or delete (ADR-0018)."""


class ErrorBody(_Out):
    code: str
    message: str
    param: str | None = None
    fields: dict[str, str] | None = None
    """``validation_failed``: every invalid field with its message (``""`` = whole form)."""
    current: RowOut | None = None
    """``conflict``: the row as it is now, so the client can show what changed."""


class Problem(_Out):
    error: ErrorBody


class CountOut(_Out):
    value: int | None
    exact: bool
    method: CountMethod


class ListOut(_Out):
    rows: list[RowOut]
    next_cursor: str | None
    prev_cursor: str | None
    pagination: Literal["keyset", "offset"]
    count: CountOut | None


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pks: list[str] = Field(min_length=1, max_length=MAX_ACTION_ROWS)


class ActionOut(_Out):
    count: int
    message: str | None


class HistoryEntry(_Out):
    id: int
    at: datetime
    actor_id: str
    actor_email: str
    action: str
    """``create``, ``update``, ``delete`` or ``action:<name>``."""
    changes: dict[str, list[Any]]
    """``{field: [old, new]}``; values of hidden columns are ``"[hidden]"``."""


class HistoryOut(_Out):
    entries: list[HistoryEntry]


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _field(c: CompiledAdmin, f: FieldMeta) -> FieldSchema:
    ops = list(f.field_type.filter_ops) if f.name in c.filter_allowed else []
    if ops and f.nullable:
        ops.append("isnull")
    write = c.write.fields.get(f.name)
    return FieldSchema(
        name=f.name,
        label=c.labels[f.name],
        kind=f.kind,
        widget=f.field_type.widget_key,
        widget_options=f.field_type.widget_options(),
        nullable=f.nullable,
        primary_key=f.primary_key,
        sortable=f.name in c.sort_allowed,
        filter_ops=ops,
        enum_values=list(f.enum_values) if f.enum_values else None,
        max_length=f.max_length,
        tz_aware=f.tz_aware,
        writable=write is not None,
        required=write is not None and write.required,
    )


_NO_PERMISSIONS = ModelPermissions(view=False, add=False, change=False, delete=False)


def model_schema(admin: ModelAdmin, slug_for: dict[type[Any], str]) -> ModelSchema:
    """Describe one admin for the UI. ``slug_for`` maps registered models to their slugs.

    The result holds no permissions or actions: they depend on the viewer and are filled
    in per request with ``for_viewer``.
    """
    c = admin.compiled
    relations = {r.name: r for r in (*c.detail_relations, *c.list_relations)}
    return ModelSchema(
        slug=c.slug,
        name=admin.display_name,
        name_plural=admin.display_name_plural,
        pk=[p.name for p in c.meta.pk],
        label_field=c.label.name,
        fields=[_field(c, f) for f in c.detail_fields],
        relations=[
            RelationSchema(
                name=r.name,
                label=c.labels.get(r.name, _humanize(r.name)),
                local_field=r.local.name,
                target=slug_for.get(r.target),
            )
            for r in relations.values()
        ],
        list_display=list(c.list_display),
        list_filter=list(c.filter_fields),
        searchable=bool(c.search),
        default_sort=list(c.default_sort),
        per_page=admin.list_per_page,
        permissions=_NO_PERMISSIONS,
        actions=[],
    )


async def for_viewer(base: ModelSchema, admin: ModelAdmin, ctx: AdminContext) -> ModelSchema:
    """``base`` with the viewer's permissions and runnable actions (call only if they can view)."""
    permissions = ModelPermissions(
        view=True,
        add=await admin.has_add_permission(ctx),
        change=await admin.has_change_permission(ctx),
        delete=await admin.has_delete_permission(ctx),
    )
    actions = [
        ActionSchema(name=a.name, label=a.label, confirm=a.confirm, destructive=a.destructive)
        for a in admin.compiled.actions.values()
        if await admin.has_action_permission(ctx, a)
    ]
    return base.model_copy(update={"permissions": permissions, "actions": actions})
