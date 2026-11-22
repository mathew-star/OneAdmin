"""Operation middleware: cross-cutting behaviour around every admin operation (ADR-0020).

    @admin.middleware
    async def notify(op: Operation, call_next: CallNext) -> Any:
        result = await call_next()
        if op.kind == "delete":
            await slack.post(f"{op.ctx.identity.email} deleted {op.slug} {op.pk}")
        return result

**Where it sits.** Middleware wraps the *whole* operation. Inside ``call_next()`` run, in
order: scoping, permission checks, validation, the transaction, the audit entry, the commit.
This means:
- Middleware can add behaviour (notifications, webhooks, metrics, extra audit sinks,
  maintenance windows) but can't skip the core guarantees.
- When ``call_next()`` returns from a write, the change is **committed**. Work that must be
  atomic with the change belongs in ``before_save``/``after_save`` instead.
- Raising stops the operation. A ``oneadmin.core.errors.WriteError`` subclass (for example
  ``PermissionDenied``) becomes the matching HTTP error.

**Order.** The first registered middleware is the outermost.

**What ``call_next()`` returns, per kind:**
- ``list``: ``ListResult``
- ``count``: ``Count``
- ``get``: ``WireRow | None``
- ``history``: ``list[AuditEntry] | None``
- ``create`` / ``update``: ``WireRow``
- ``delete``: ``None``
- ``action``: ``ActionResult``
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from oneadmin.core.context import AdminContext
    from oneadmin.core.model_admin import ModelAdmin
    from oneadmin.core.service import ListParams

T = TypeVar("T")

OperationKind = Literal["list", "count", "get", "history", "create", "update", "delete", "action"]
READS: frozenset[OperationKind] = frozenset({"list", "count", "get", "history"})


@dataclass(frozen=True, slots=True)
class Operation:
    """One admin operation, as middleware sees it."""

    kind: OperationKind
    admin: ModelAdmin[Any]
    ctx: AdminContext
    pk: str | None = None
    """``get``, ``history``, ``update``, ``delete``: the encoded primary key."""
    pks: tuple[str, ...] = ()
    """``action``: the selected rows."""
    action: str | None = None
    """``action``: its name."""
    payload: Mapping[str, Any] | None = field(default=None, repr=False)
    """``create``, ``update``: the client's input, before validation."""
    params: ListParams | None = field(default=None, repr=False)
    """``list``, ``count``: sort, search, filters and paging, before validation."""

    @property
    def slug(self) -> str:
        return self.admin.compiled.slug

    @property
    def model(self) -> type[Any]:
        return self.admin.compiled.model

    @property
    def is_write(self) -> bool:
        return self.kind not in READS


CallNext = Callable[[], Awaitable[Any]]
Middleware = Callable[[Operation, CallNext], Awaitable[Any]]


class OperationRunner:
    """Runs operations through a site's middleware chain (no chain: a direct call)."""

    def __init__(self, middleware: Sequence[Middleware] = ()) -> None:
        self._middleware = tuple(middleware)

    async def run(self, op: Operation, call: Callable[[], Awaitable[T]]) -> T:
        handler: CallNext = call
        for mw in reversed(self._middleware):
            handler = _bind(mw, op, handler)
        result: T = await handler()
        return result


def _bind(mw: Middleware, op: Operation, call_next: CallNext) -> CallNext:
    async def step() -> Any:
        return await mw(op, _once(call_next))

    return step


def _once(call_next: CallNext) -> CallNext:
    """``call_next`` may run the rest of the chain at most once (a second write would run
    the operation twice)."""
    used = False

    async def guarded() -> Any:
        nonlocal used
        if used:
            raise RuntimeError("call_next() was called twice in one middleware")
        used = True
        return await call_next()

    return guarded
