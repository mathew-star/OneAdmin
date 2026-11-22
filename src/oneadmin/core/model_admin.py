"""``ModelAdmin``: declarative, Django-style configuration for one registered model.

There are two kinds of state, kept strictly apart:

* **Options** are class attributes that users set on their subclass (``list_display``, ...).
* **Compiled state** is an immutable ``CompiledAdmin``, built once at startup from the options
  and the model's introspected metadata. It lives on ``ModelAdmin.compiled`` so it can never
  collide with attributes a user defines on their own subclass.

Every option is validated during compilation. Mistakes raise ``ConfigurationError`` at app
startup with a message that says what to change. They never surface at request time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Generic, final

from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import UnaryExpression
from typing_extensions import TypeVar

from oneadmin.auth.permissions import action_codename, codename
from oneadmin.core.actions import ActionSpec
from oneadmin.core.compiler import CompiledAdmin, Compiler, RelationSpec
from oneadmin.core.fields import FieldType
from oneadmin.core.query.counting import Strategy

if TYPE_CHECKING:
    from oneadmin.core._typing import AnySelect
    from oneadmin.core.context import AdminContext
    from oneadmin.core.conventions import Convention

__all__ = ["CompiledAdmin", "FieldRef", "ModelAdmin", "OrderRef", "RelationSpec"]

M = TypeVar("M", default=Any)
"""The registered model class; ``ModelAdmin[Post]`` types the hooks' ``obj``."""

FieldRef = str | QueryableAttribute[Any]
"""A column or relationship: its name (``"title"``) or the attribute (``Post.title``)."""
OrderRef = str | QueryableAttribute[Any] | UnaryExpression[Any]
"""A sort key: ``"-created_at"``, ``Post.created_at`` or ``Post.created_at.desc()``."""


class ModelAdmin(Generic[M]):
    """Configure how one model appears in the admin.

    Subclass it and register it::

        @site.register(Post)
        class PostAdmin(ModelAdmin):
            list_display = ("id", "title", "author", "published")
            list_filter = ("published",)
            search_fields = ("title",)
            ordering = ("-created_at",)

    Every option is optional. ``site.register(Post)`` alone gives sensible defaults.

    Options that name columns accept strings or the model's attributes; attributes give
    editor completion and survive renames::

        class PostAdmin(ModelAdmin[Post]):
            list_display = (Post.id, Post.title, Post.author)
            ordering = (Post.created_at.desc(),)

    Site-wide rules (``AdminSite(conventions=[...])``) apply before these options; the
    options win. ``oneadmin explain <slug>`` shows the result and where each value came from.
    """

    # ---- options -----------------------------------------------------------------------
    list_display: ClassVar[Sequence[FieldRef] | None] = None
    """Columns and many-to-one relationship names shown in the list.
    Default: the first eight short columns (no long text, JSON or binary)."""

    list_filter: ClassVar[Sequence[FieldRef]] = ()
    """Columns clients may filter on. Anything not listed is rejected with HTTP 400."""

    search_fields: ClassVar[Sequence[FieldRef]] = ()
    """Columns searched by the search box, Django syntax: ``"^name"`` (starts with),
    ``"=id"`` (exact), ``"name"`` (contains, case-insensitive)."""

    ordering: ClassVar[Sequence[OrderRef]] = ()
    """Default sort, e.g. ``("-created_at",)``. Default: newest primary key first."""

    sortable_fields: ClassVar[Sequence[FieldRef] | None] = None
    """Columns clients may sort by. Default: the columns in ``list_display`` plus ``ordering``.
    Sorting should be backed by an index; ``oneadmin check`` warns when it isn't."""

    fields: ClassVar[Sequence[FieldRef] | None] = None
    """Explicit allow-list of columns for the detail view. When set, it also overrides the
    default hiding of credential-like columns (``*password*``, ``*token*``, ...)."""

    exclude: ClassVar[Sequence[FieldRef]] = ()
    """Columns never sent to clients, in any view."""

    readonly_fields: ClassVar[Sequence[FieldRef]] = ()
    """Visible columns clients may not write. Generated columns (identity, computed,
    auto-increment PKs) and JSON/array/binary columns are always read-only (ADR-0018)."""

    blank_fields: ClassVar[Sequence[FieldRef]] = ()
    """Required text columns that may nevertheless be saved as ``""``. By default an empty
    or whitespace-only value is refused for required (NOT NULL, no default) text fields."""

    field_types: ClassVar[Mapping[FieldRef, FieldType]] = {}
    """Field types for specific columns, e.g. ``{Product.price: MoneyField("EUR")}``.
    They win over site conventions and the defaults from the SQL type."""

    labels: ClassVar[Mapping[FieldRef, str]] = {}
    """Display labels, e.g. ``{Post.created_at: "Published on"}``. Default: the name in words."""

    ignore_conventions: ClassVar[Sequence[str]] = ()
    """Ids of site conventions that don't apply to this admin."""

    bulk_delete: ClassVar[bool] = True
    """Offer the built-in ``delete_selected`` action (it needs the delete permission)."""

    label_field: ClassVar[FieldRef | None] = None
    """Column used to label rows of this model elsewhere (e.g. a post's author).
    Default: the first of name/title/username/email/label/slug/code, else the PK."""

    list_per_page: ClassVar[int] = 50

    count_strategy: ClassVar[Strategy] = "auto"
    """How list totals are computed: ``auto`` (estimate for big unfiltered tables, else capped),
    ``exact``, ``capped``, ``estimate`` or ``none``. See ADR-0004."""

    count_concurrently: ClassVar[bool] = True
    """Run the count on a second connection in parallel with the page query."""

    name: ClassVar[str | None] = None
    """URL slug. Default: the table name. Needed when one model is registered twice."""

    verbose_name: ClassVar[str | None] = None
    verbose_name_plural: ClassVar[str | None] = None

    # ---- hooks -------------------------------------------------------------------------
    async def get_queryset(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
        """Scope every read and write of this model: lists, counts, detail, the target rows of
        updates, deletes and actions, and labels pointing at it.

        Return ``stmt`` with extra ``WHERE`` clauses. For example, tenant isolation::

            async def get_queryset(self, ctx, stmt):
                return stmt.where(Order.tenant_id == ctx.identity.extra["tenant_id"])

        ``stmt`` may already contain joins; only add filters on this model's columns.
        Site-wide ``scope_by`` conventions are applied before this hook.
        """
        return stmt

    @final
    async def apply_scope(self, ctx: AdminContext, stmt: AnySelect) -> AnySelect:
        """The only way OneAdmin scopes a statement: ``scope_by`` conventions, then
        ``get_queryset``. Every read and write path calls it (CLAUDE.md invariant 4).
        Override ``get_queryset``, never this."""
        for scope in self.compiled.scopes:
            clause = await scope.clause(ctx)
            if clause is not None:
                stmt = stmt.where(clause)
        return await self.get_queryset(ctx, stmt)

    async def has_view_permission(self, ctx: AdminContext) -> bool:
        """Whether ``ctx.identity`` may see this model at all.

        Default: superusers, and holders of ``<slug>.view`` or ``<slug>.change`` (ADR-0019).
        Without it the model is absent from the schema and its endpoints answer 404.
        """
        slug = self.compiled.slug
        return ctx.identity.has_perm(codename(slug, "view")) or ctx.identity.has_perm(
            codename(slug, "change")
        )

    async def has_add_permission(self, ctx: AdminContext) -> bool:
        """Whether ``ctx.identity`` may create rows. Default: ``<slug>.add``."""
        return ctx.identity.has_perm(codename(self.compiled.slug, "add"))

    async def has_change_permission(self, ctx: AdminContext, obj: M | None = None) -> bool:
        """Whether ``ctx.identity`` may change rows (``obj=None``) or this row.

        Default: ``<slug>.change``. Override to restrict per row, e.g. "only your own drafts".
        It is called with ``obj`` for every row of an update or bulk action.
        """
        return ctx.identity.has_perm(codename(self.compiled.slug, "change"))

    async def has_delete_permission(self, ctx: AdminContext, obj: M | None = None) -> bool:
        """Whether ``ctx.identity`` may delete rows (``obj=None``) or this row.
        Default: ``<slug>.delete``."""
        return ctx.identity.has_perm(codename(self.compiled.slug, "delete"))

    async def has_action_permission(
        self, ctx: AdminContext, action: ActionSpec, obj: M | None = None
    ) -> bool:
        """Whether ``ctx.identity`` may run ``action`` (on ``obj``, when given).

        Delegates to the permission the action declares: ``has_change_permission`` for
        ``permission="change"``, and so on. ``"custom"`` checks ``<slug>.action.<name>``.
        """
        match action.permission:
            case "view":
                return await self.has_view_permission(ctx)
            case "add":
                return await self.has_add_permission(ctx)
            case "change":
                return await self.has_change_permission(ctx, obj)
            case "delete":
                return await self.has_delete_permission(ctx, obj)
            case "custom":
                return ctx.identity.has_perm(action_codename(self.compiled.slug, action.name))

    async def clean(self, ctx: AdminContext, data: dict[str, Any], obj: M | None) -> dict[str, Any]:
        """Validate and adjust parsed input before it is applied. ``obj`` is ``None`` on create.

        ``data`` holds only the fields the client sent, already typed. Raise
        ``ValidationError({"field": "message"})`` to reject it; return the (possibly changed)
        dict to accept it. Runs inside the write's transaction, so ``ctx.session`` sees it.
        """
        return data

    async def before_save(self, ctx: AdminContext, obj: M, *, created: bool) -> None:
        """Called after the input is applied to ``obj`` and before it is flushed.
        Set server-side values here (e.g. ``obj.updated_by = ctx.identity.id``)."""

    async def after_save(self, ctx: AdminContext, obj: M, *, created: bool) -> None:
        """Called after the row is flushed and passed the scope check, before commit.
        Raising rolls back the whole change, including its audit entry."""

    async def before_delete(self, ctx: AdminContext, obj: M) -> None:
        """Called before ``obj`` is deleted (also by ``delete_selected``). Raise
        ``ValidationError`` to refuse, e.g. "can't delete a paid order"."""

    # ---- compiled state ----------------------------------------------------------------
    _compiled: CompiledAdmin | None = None

    @property
    def compiled(self) -> CompiledAdmin:
        if self._compiled is None:
            raise RuntimeError(f"{type(self).__name__} is not compiled; build the AdminSite first")
        return self._compiled

    @property
    def model(self) -> type[Any]:
        """The registered model class (available once the site is built)."""
        return self.compiled.model

    @property
    def display_name(self) -> str:
        """``verbose_name``, or the class name in words: ``OrderLine`` -> ``Order line``."""
        return self.verbose_name or humanize_class_name(self.compiled.model.__name__)

    @property
    def display_name_plural(self) -> str:
        """``verbose_name_plural``, or a regular English plural of ``display_name``.

        Irregular nouns (``Person`` -> ``People``) need ``verbose_name_plural``.
        """
        return self.verbose_name_plural or pluralize(self.display_name)

    def compile(self, model: type[Any], conventions: Sequence[Convention] = ()) -> CompiledAdmin:
        """Validate the options against ``model`` and freeze the result (called by the site)."""
        self._compiled = Compiler(self, model, conventions).run()
        return self._compiled


# ---- naming ------------------------------------------------------------------------------
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize_class_name(name: str) -> str:
    """``OrderLine`` -> ``Order line``; ``HTTPLog`` -> ``HTTP log``; ``Item`` -> ``Item``."""
    words = _CAMEL_BOUNDARY.sub(" ", name).split()
    rest = [w if w.isupper() and len(w) > 1 else w.lower() for w in words[1:]]
    return " ".join([*words[:1], *rest])


def pluralize(noun: str) -> str:
    """Regular English plurals of the last word: category -> categories, box -> boxes."""
    lower = noun.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return f"{noun}es"
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return f"{noun[:-1]}ies"
    return f"{noun}s"
