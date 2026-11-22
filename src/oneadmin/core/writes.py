"""Write services: create, update, delete, bulk actions and row history (ADR-0018).

Every operation follows the same shape, inside **one transaction** that commits once at
the end and rolls back on any error (including errors raised by hooks):

1. Parse and validate the input (``WriteSpec``): no database access yet.
2. Load the target rows **through ``apply_scope``** (``scope_by`` conventions, then
   ``get_queryset``) with ``SELECT ... FOR UPDATE``. A row
   outside the caller's scope is indistinguishable from a missing one (``NotFound``).
3. Check permissions per row, and the ``If-Match`` version for update/delete.
4. Run ``clean``, check that written foreign keys point at rows the caller can see, apply
   the values, run ``before_save``, then flush.
5. **Scope after write:** re-select the rows through ``apply_scope``. If a row left the
   caller's scope (moved to another tenant, created for another tenant), refuse.
6. Write one audit entry per changed row, run ``after_save``, commit.

Database constraint violations surface as ``IntegrityConflict``, with the constraint name.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, literal, select, tuple_
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from oneadmin.auth import tables as t
from oneadmin.auth.service import AdminNotMigrated, is_missing_table
from oneadmin.core.actions import DELETE_SELECTED, MAX_ACTION_ROWS, ActionSpec
from oneadmin.core.context import AdminContext
from oneadmin.core.conventions import ALL
from oneadmin.core.errors import (
    Conflict,
    IntegrityConflict,
    NotFound,
    OutOfScope,
    PermissionDenied,
    PreconditionRequired,
    UnknownAction,
    ValidationError,
)
from oneadmin.core.model_admin import CompiledAdmin, ModelAdmin
from oneadmin.core.service import ReadService, WireRow
from oneadmin.core.versioning import RowVersioner
from oneadmin.core.wire import decode_pk, encode_pk, to_wire

Clock = Callable[[], datetime]
REDACTED = "[hidden]"
"""Audit value for columns the admin never shows (their names are still recorded)."""
MAX_HISTORY = 200


@dataclass(frozen=True, slots=True)
class ActionResult:
    count: int
    message: str | None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: int
    at: datetime
    actor_id: str
    actor_email: str
    action: str
    changes: dict[str, list[Any]]


class WriteService:
    """Write operations for every admin of one ``AdminSite``."""

    def __init__(
        self,
        read: ReadService,
        versions: RowVersioner,
        admins: Callable[[], Iterable[ModelAdmin]],
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._read = read
        self._versions = versions
        self._admins = admins
        self._by_table: dict[Any, ModelAdmin] | None = None
        self._clock = clock

    # ---- create / update / delete --------------------------------------------------------
    async def create(
        self, ctx: AdminContext, admin: ModelAdmin, payload: Mapping[str, Any]
    ) -> WireRow:
        """Create a row. The caller has already checked ``has_add_permission``."""
        c = admin.compiled
        payload = await self._autofill_scopes(ctx, c, payload)
        data = c.write.parse(payload, creating=True)
        async with self._transaction(ctx.session, c):
            data = await admin.clean(ctx, data, None)
            await self._check_references(ctx, c, data)
            obj = c.model(**data)
            await admin.before_save(ctx, obj, created=True)
            ctx.session.add(obj)
            await ctx.session.flush()
            await ctx.session.refresh(obj)
            pk = self._pk_of(c, obj)
            await self._require_in_scope(ctx, admin, [pk])
            await self._audit(ctx, c, "create", pk, _created(self._snapshot(c, obj)))
            await admin.after_save(ctx, obj, created=True)
        return await self._reread(ctx, admin, pk)

    async def update(
        self,
        ctx: AdminContext,
        admin: ModelAdmin,
        raw_pk: str,
        payload: Mapping[str, Any],
        if_match: str | None,
    ) -> WireRow:
        """Change the fields in ``payload`` of one row, if its version still matches."""
        c = admin.compiled
        data = c.write.parse(payload, creating=False)
        async with self._transaction(ctx.session, c):
            (obj,) = await self._load_for_update(ctx, admin, [raw_pk])
            if not await admin.has_change_permission(ctx, obj):
                raise PermissionDenied("You don't have permission to change this row.")
            await self._check_version(ctx, admin, obj, if_match)
            data = await admin.clean(ctx, data, obj)
            await self._check_references(ctx, c, data)
            before = self._snapshot(c, obj)
            for name, value in data.items():
                setattr(obj, name, value)
            await admin.before_save(ctx, obj, created=False)
            await ctx.session.flush()
            await ctx.session.refresh(obj)
            pk = self._pk_of(c, obj)
            await self._require_in_scope(ctx, admin, [pk])
            changes = _diff(before, self._snapshot(c, obj))
            if changes:
                await self._audit(ctx, c, "update", pk, changes)
            await admin.after_save(ctx, obj, created=False)
        return await self._reread(ctx, admin, pk)

    async def delete(
        self, ctx: AdminContext, admin: ModelAdmin, raw_pk: str, if_match: str | None
    ) -> None:
        """Delete one row, if its version still matches."""
        c = admin.compiled
        async with self._transaction(ctx.session, c):
            (obj,) = await self._load_for_update(ctx, admin, [raw_pk])
            if not await admin.has_delete_permission(ctx, obj):
                raise PermissionDenied("You don't have permission to delete this row.")
            await self._check_version(ctx, admin, obj, if_match)
            await self._delete_rows(ctx, admin, [obj], action="delete")

    # ---- bulk actions --------------------------------------------------------------------
    async def run_action(
        self, ctx: AdminContext, admin: ModelAdmin, name: str, raw_pks: Sequence[str]
    ) -> ActionResult:
        """Run a bulk action on the selected rows (all or nothing)."""
        c = admin.compiled
        spec = c.actions.get(name)
        if spec is None:
            raise UnknownAction(f"{c.slug!r} has no action {name!r}.", param="name")
        unique = list(dict.fromkeys(raw_pks))
        if not 1 <= len(unique) <= MAX_ACTION_ROWS:
            raise ValidationError({"pks": f"select between 1 and {MAX_ACTION_ROWS} rows"})
        async with self._transaction(ctx.session, c):
            rows = await self._load_for_update(ctx, admin, unique)
            for obj in rows:
                if not await admin.has_action_permission(ctx, spec, obj):
                    raise PermissionDenied(
                        f"You don't have permission to run {spec.label!r} on every selected row."
                    )
            if spec.name == DELETE_SELECTED:
                await self._delete_rows(ctx, admin, rows, action=f"action:{spec.name}")
                return ActionResult(len(rows), f"Deleted {len(rows)} {_noun(admin, len(rows))}.")
            message = await self._run_custom(ctx, admin, spec, rows)
        return ActionResult(len(rows), message)

    async def _run_custom(
        self, ctx: AdminContext, admin: ModelAdmin, spec: ActionSpec, rows: list[Any]
    ) -> str | None:
        c = admin.compiled
        before = {id(obj): (self._pk_of(c, obj), self._snapshot(c, obj)) for obj in rows}
        if spec.method is None:  # only the built-in delete_selected has no method
            raise UnknownAction(f"action {spec.name!r} has no implementation")
        message = await getattr(admin, spec.method)(ctx, rows)
        if message is not None and not isinstance(message, str):
            raise TypeError(f"action {spec.name!r} must return a message string or None")
        # Rows of this model the action added are held to the same rules as the selected ones.
        created = [obj for obj in ctx.session.new if isinstance(obj, c.model)]
        await ctx.session.flush()
        deleted = {id(obj) for obj in rows if _is_deleted(obj)}
        survivors = [obj for obj in rows if id(obj) not in deleted]
        for obj in (*survivors, *created):
            await ctx.session.refresh(obj)
        await self._require_in_scope(
            ctx, admin, [self._pk_of(c, obj) for obj in (*survivors, *created)]
        )
        action = f"action:{spec.name}"
        for obj in rows:
            pk, old = before[id(obj)]
            changes = _removed(old) if id(obj) in deleted else _diff(old, self._snapshot(c, obj))
            if changes:
                await self._audit(ctx, c, action, pk, changes)
        for obj in created:
            await self._audit(ctx, c, action, self._pk_of(c, obj), _created(self._snapshot(c, obj)))
        return message

    # ---- history -------------------------------------------------------------------------
    async def history(
        self, ctx: AdminContext, admin: ModelAdmin, raw_pk: str, *, limit: int = 50
    ) -> list[AuditEntry] | None:
        """Audit entries of one row, newest first; ``None`` if the row isn't visible."""
        c = admin.compiled
        try:
            pk = encode_pk(c.meta, decode_pk(c.meta, raw_pk))  # canonical form
        except (ValueError, KeyError):
            return None
        if not await self._visible(ctx, admin, [pk]):
            return None
        stmt = (
            select(t.audit_log)
            .where(t.audit_log.c.model == c.slug, t.audit_log.c.object_pk == pk)
            .order_by(t.audit_log.c.at.desc(), t.audit_log.c.id.desc())
            .limit(min(max(limit, 1), MAX_HISTORY))
        )
        try:
            rows = (await ctx.session.execute(stmt)).mappings().all()
        except (ProgrammingError, OperationalError) as exc:
            if is_missing_table(exc):
                raise AdminNotMigrated() from exc
            raise
        return [
            AuditEntry(
                r["id"], r["at"], r["actor_id"], r["actor_email"], r["action"], dict(r["changes"])
            )
            for r in rows
        ]

    # ---- steps ---------------------------------------------------------------------------
    @asynccontextmanager
    async def _transaction(self, session: AsyncSession, c: CompiledAdmin) -> AsyncIterator[None]:
        """Commit once on success; roll back everything (hooks' work included) on error.

        Database errors can surface at any statement (SQLAlchemy autoflushes before queries),
        so they are translated here, once: constraint violations become
        ``IntegrityConflict`` and missing OneAdmin tables ``AdminNotMigrated``.
        """
        try:
            yield
            await session.commit()
        except BaseException as exc:
            await session.rollback()
            if isinstance(exc, IntegrityError):
                raise _integrity_conflict(exc, c) from None
            if isinstance(exc, ProgrammingError | OperationalError) and is_missing_table(exc):
                raise AdminNotMigrated() from exc
            raise

    async def _load_for_update(
        self, ctx: AdminContext, admin: ModelAdmin, raw_pks: Sequence[str]
    ) -> list[Any]:
        """The rows, through the admin's scope, locked. Any missing one -> ``NotFound``."""
        c = admin.compiled
        keys: list[tuple[Any, ...]] = []
        for raw in raw_pks:
            try:
                keys.append(decode_pk(c.meta, raw))
            except (ValueError, KeyError):
                raise NotFound(_missing(admin, len(raw_pks))) from None
        stmt = await admin.apply_scope(ctx, select(c.model))
        stmt = stmt.where(_pk_in(c, keys)).with_for_update(of=c.model)
        rows = list((await ctx.session.execute(stmt)).scalars().unique())
        if len(rows) != len(set(keys)):
            raise NotFound(_missing(admin, len(raw_pks)))
        order = {key: i for i, key in enumerate(keys)}
        rows.sort(key=lambda obj: order.get(self._pk_values(c, obj), 0))
        return rows

    async def _check_version(
        self, ctx: AdminContext, admin: ModelAdmin, obj: Any, if_match: str | None
    ) -> None:
        c = admin.compiled
        if not if_match:
            raise PreconditionRequired(
                "Send the row's current version in the If-Match header.", param="If-Match"
            )
        current = self._versions.of_instance(c, obj)
        if not self._versions.matches(current, if_match.strip().strip('"')):
            row = await self._read.get(ctx, admin, self._pk_of(c, obj))
            raise Conflict(
                "This row was changed by someone else since you loaded it. "
                "Review the current values and try again.",
                current=row,
            )

    async def _autofill_scopes(
        self, ctx: AdminContext, c: CompiledAdmin, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Add ``scope_by`` columns the client omitted, from the caller's single scope value,
        so a tenant user creates rows in their own tenant without sending ``tenant_id``.

        Runs before validation (so the column counts as present) and adds the value in
        wire form, so it is parsed and validated like client input. Scope-after-write
        still checks the result.
        """
        filled = dict(payload)
        for scope in c.scopes:
            name = scope.field.name
            if not scope.rule.autofill or name in filled or name not in c.write.fields:
                continue
            value = await scope.rule.resolve(ctx)
            if value is not None and value is not ALL and not _is_collection(value):
                filled[name] = scope.field.field_type.to_wire(value)
        return filled

    async def _check_references(
        self, ctx: AdminContext, c: CompiledAdmin, data: Mapping[str, Any]
    ) -> None:
        """A written foreign key must point at a row the caller can see in the target admin.

        Driven by the columns' ``ForeignKey`` metadata, so it covers FK columns with and
        without an ORM ``relationship()``. Targets without a registered admin are left to the
        database's own FK constraint.
        """
        errors: dict[str, str] = {}
        for name, value in data.items():
            if value is None:
                continue
            for fk in c.meta.fields[name].column.foreign_keys:
                target = self._admin_for_table(fk.column.table)
                if target is None:
                    continue
                stmt = select(literal(1)).select_from(target.compiled.model)
                stmt = (await target.apply_scope(ctx, stmt)).where(fk.column == value).limit(1)
                if (await ctx.session.execute(stmt)).first() is None:
                    errors[name] = f"no {target.display_name} with this key"
        if errors:
            raise ValidationError(errors)

    def _admin_for_table(self, table: Any) -> ModelAdmin | None:
        """The primary admin of the model mapped to ``table`` (built once, on first use)."""
        if self._by_table is None:
            by_table: dict[Any, ModelAdmin] = {}
            for admin in self._admins():
                by_table.setdefault(admin.compiled.meta.mapper.local_table, admin)
            self._by_table = by_table
        return self._by_table.get(table)

    async def _require_in_scope(
        self, ctx: AdminContext, admin: ModelAdmin, pks: Sequence[str]
    ) -> None:
        if pks and not await self._visible(ctx, admin, pks):
            raise OutOfScope(
                "This change would move the row outside what you're allowed to see "
                "(for example, into another tenant)."
            )

    async def _visible(self, ctx: AdminContext, admin: ModelAdmin, pks: Sequence[str]) -> bool:
        """Whether every row in ``pks`` is visible through ``apply_scope``."""
        c = admin.compiled
        keys = {decode_pk(c.meta, pk) for pk in pks}
        stmt = select(*(p.expr for p in c.meta.pk)).select_from(c.model)
        stmt = (await admin.apply_scope(ctx, stmt)).where(_pk_in(c, list(keys)))
        found = {tuple(row) for row in (await ctx.session.execute(stmt)).all()}
        return keys <= found

    async def _delete_rows(
        self, ctx: AdminContext, admin: ModelAdmin, rows: Iterable[Any], *, action: str
    ) -> None:
        c = admin.compiled
        for obj in rows:
            await admin.before_delete(ctx, obj)
            pk, old = self._pk_of(c, obj), self._snapshot(c, obj)
            await ctx.session.delete(obj)
            await self._audit(ctx, c, action, pk, _removed(old))
        await ctx.session.flush()

    async def _audit(
        self, ctx: AdminContext, c: CompiledAdmin, action: str, pk: str, changes: dict[str, Any]
    ) -> None:
        identity = ctx.identity
        client = getattr(ctx.request, "client", None)
        ip = getattr(client, "host", None)
        # A Core insert on the request's session: same transaction as the change it records.
        await ctx.session.execute(
            insert(t.audit_log).values(
                at=self._clock(),
                actor_id=str(identity.id)[:64],
                actor_email=identity.email[:254],
                action=action,
                model=c.slug,
                object_pk=pk[:512],
                changes=changes,
                ip=ip if isinstance(ip, str) else None,
            )
        )

    async def _reread(self, ctx: AdminContext, admin: ModelAdmin, pk: str) -> WireRow:
        row = await self._read.get(ctx, admin, pk)
        if row is None:  # committed, but a concurrent change hid it again: report what we can
            raise NotFound("The row was saved but is no longer visible.")
        return row

    # ---- helpers -------------------------------------------------------------------------
    def _snapshot(self, c: CompiledAdmin, obj: Any) -> dict[str, Any]:
        """Wire values of every mapped column; columns hidden from the admin are redacted."""
        visible = {f.name for f in c.detail_fields}
        return {
            name: to_wire(getattr(obj, name)) if name in visible else _Redacted(getattr(obj, name))
            for name in c.meta.fields
        }

    def _pk_values(self, c: CompiledAdmin, obj: Any) -> tuple[Any, ...]:
        return tuple(getattr(obj, p.name) for p in c.meta.pk)

    def _pk_of(self, c: CompiledAdmin, obj: Any) -> str:
        return encode_pk(c.meta, self._pk_values(c, obj))


class _Redacted:
    """A hidden column's value: compared for change detection, never written to the audit."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Redacted) and bool(self.value == other.value)

    def __hash__(self) -> int:
        return 0


def _diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[Any]]:
    changes: dict[str, list[Any]] = {}
    for name, old in before.items():
        new = after.get(name)
        if old != new:
            changes[name] = [_audit_value(old), _audit_value(new)]
    return changes


def _audit_value(value: Any) -> Any:
    return REDACTED if isinstance(value, _Redacted) else value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, _Redacted) and value.value is None)


def _created(snapshot: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Audit changes of a new row: every non-empty value, from ``None``."""
    return {k: [None, _audit_value(v)] for k, v in snapshot.items() if not _is_empty(v)}


def _removed(snapshot: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Audit changes of a deleted row: every non-empty value, to ``None``."""
    return {k: [_audit_value(v), None] for k, v in snapshot.items() if not _is_empty(v)}


def _is_deleted(obj: Any) -> bool:
    state = sa_inspect(obj)
    return bool(state.deleted or state.was_deleted)


def _is_collection(value: Any) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, str | bytes)


def _pk_in(c: CompiledAdmin, keys: Sequence[tuple[Any, ...]]) -> Any:
    if len(c.meta.pk) == 1:
        return c.meta.pk[0].expr.in_([k[0] for k in keys])
    return tuple_(*(p.expr for p in c.meta.pk)).in_(keys)


def _missing(admin: ModelAdmin, n: int) -> str:
    if n == 1:
        return f"{admin.display_name} not found."
    return (
        "Some of the selected rows no longer exist, or aren't visible to you. Reload and try again."
    )


def _noun(admin: ModelAdmin, n: int) -> str:
    return admin.display_name.lower() if n == 1 else admin.display_name_plural.lower()


_SQLITE_CONSTRAINT = re.compile(
    r"(UNIQUE|NOT NULL|CHECK|FOREIGN KEY) constraint failed(?::\s*(\S+))?"
)


_PG_KEY_DETAIL = re.compile(r"Key \(([^)]*)\)=")


def _integrity_conflict(exc: IntegrityError, c: CompiledAdmin) -> IntegrityConflict:
    """A client-safe description of a constraint violation: its name, and the field if known.

    Values from the database's message are never echoed (they could belong to rows the user
    can't see); only the constraint and column names are.
    """
    orig: Any = exc.orig
    sources = (orig, getattr(orig, "__cause__", None), getattr(orig, "diag", None))
    name = next((n for src in sources if (n := getattr(src, "constraint_name", None))), None)
    detail = next(
        (
            d
            for src in sources
            for attr in ("detail", "message_detail")
            if (d := getattr(src, attr, None))
        ),
        None,
    )
    param = _constraint_field(c, name)
    if param is None and isinstance(detail, str):  # PostgreSQL: "Key (sku)=(...) already exists."
        match = _PG_KEY_DETAIL.search(detail)
        columns = [col.strip().strip('"') for col in match.group(1).split(",")] if match else []
        param = _field_for_column(c, columns[0]) if len(columns) == 1 else None
    if name is None:  # SQLite: "UNIQUE constraint failed: posts.slug"
        match = _SQLITE_CONSTRAINT.search(str(orig))
        if match:
            name = match.group(1).lower()
            column = (match.group(2) or "").rpartition(".")[2]
            param = param or _field_for_column(c, column)
    what = f" ({name})" if name else ""
    return IntegrityConflict(
        f"The database rejected this change: it violates a constraint{what}. "
        "For example, a value that must be unique is already used, or the row is still "
        "referenced by other rows.",
        param=param,
    )


def _field_for_column(c: CompiledAdmin, column: str) -> str | None:
    return next((f.name for f in c.meta.fields.values() if f.column.key == column), None)


def _constraint_field(c: CompiledAdmin, name: str | None) -> str | None:
    """The single column a named constraint or unique index covers, if it is a field."""
    if name is None:
        return None
    table: Any = c.meta.mapper.local_table
    for item in (*getattr(table, "constraints", ()), *getattr(table, "indexes", ())):
        if getattr(item, "name", None) == name:
            columns = [col.key for col in item.columns]
            return _field_for_column(c, columns[0]) if len(columns) == 1 else None
    return None
