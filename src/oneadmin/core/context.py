"""Per-request context passed explicitly to every ``ModelAdmin`` hook (ADR-0006)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from oneadmin.auth.backend import AdminIdentity


@dataclass(frozen=True, slots=True)
class AdminContext:
    identity: AdminIdentity
    session: AsyncSession
    """The request's raw session. Hook code is trusted and owns its extra writes.

    The admin write path audits and scope-checks its target rows, not arbitrary SQL or
    unrelated rows changed through this session.
    """
    request: Any = None
    """The web framework's request object (a Starlette ``Request``), for advanced hooks."""
