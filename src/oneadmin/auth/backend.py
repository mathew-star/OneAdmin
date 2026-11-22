"""Authentication backend protocol.

The built-in password backend (M3) implements this protocol. Apps can also plug in their own
(SSO, an existing user table). It is framework-neutral: ``request`` is whatever the web layer
passes (a Starlette ``Request`` in practice), and is typed ``Any`` so this module stays free of
web imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from oneadmin.auth.service import AuthService


@dataclass(frozen=True, slots=True)
class AdminIdentity:
    """Who is making the request. Hooks receive it via ``AdminContext.identity``."""

    id: str
    email: str
    is_superuser: bool = False
    permissions: frozenset[str] = frozenset()
    """Granted permission codenames, e.g. ``{"orders.view", "orders.change"}`` (ADR-0019).
    Superusers implicitly have every permission. Custom backends fill this in themselves."""
    extra: dict[str, Any] = field(default_factory=dict)
    """App-specific attributes (e.g. ``tenant_id``) for ``get_queryset`` / permission hooks."""

    def has_perm(self, codename: str) -> bool:
        """Whether this identity holds ``codename``, directly or through ``<model>.*``."""
        if self.is_superuser or codename in self.permissions:
            return True
        model, sep, _ = codename.partition(".")
        return bool(sep) and f"{model}.*" in self.permissions


@runtime_checkable
class AuthBackend(Protocol):
    async def authenticate(self, request: Any) -> AdminIdentity | None:
        """Return the identity for this request, or ``None`` if unauthenticated."""
        ...


class SessionCookieBackend:
    """The built-in backend: an opaque session token in an HttpOnly cookie (ADR-0005)."""

    def __init__(self, service: AuthService, cookie_name: str) -> None:
        self.service = service
        self.cookie_name = cookie_name

    def token(self, request: Any) -> str | None:
        """The raw session token from the request's cookie, if any."""
        value = request.cookies.get(self.cookie_name)
        return value if isinstance(value, str) and value else None

    async def authenticate(self, request: Any) -> AdminIdentity | None:
        return await self.service.resolve(self.token(request))
