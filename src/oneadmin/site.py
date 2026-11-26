"""``AdminSite``: the object an application creates, registers models on, and mounts.

A site owns all of its state (registry, secrets, services). There is no module-level mutable
state, so several sites can live in one process (CLAUDE.md invariant 1).
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Any, TypeVar

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import configure_mappers

from oneadmin.api import errors
from oneadmin.api.auth_routes import build_auth_router
from oneadmin.api.body_limit import BodyLimitMiddleware
from oneadmin.api.dev import DevModeMiddleware
from oneadmin.api.router import build_router
from oneadmin.api.security import SecurityHeadersMiddleware
from oneadmin.auth import migrate as migrations
from oneadmin.auth.backend import AuthBackend, SessionCookieBackend
from oneadmin.auth.service import AuthService, AuthSettings
from oneadmin.core.autoconfig import suggest
from oneadmin.core.conventions import Convention
from oneadmin.core.errors import ConfigurationError
from oneadmin.core.model_admin import ModelAdmin
from oneadmin.core.operations import Middleware, OperationRunner
from oneadmin.core.query.cursor import CursorCodec
from oneadmin.core.service import ReadService
from oneadmin.core.versioning import RowVersioner
from oneadmin.core.writes import WriteService
from oneadmin.ui.spa import mount_ui

log = logging.getLogger("oneadmin")

A = TypeVar("A", bound=type[ModelAdmin])

MIN_SECRET_LENGTH = 32
DEV_ENV_VAR = "ONEADMIN_DEV"
#: Development-only key. It is public because dev mode is for locally bound servers,
#: and the key signs cursors and derives CSRF tokens (which also need the
#: unguessable session token); sessions themselves are random and stored hashed.
DEV_SECRET_KEY = "oneadmin-development-only-key-never-use-in-production"  # noqa: S105 - public by design, see above


class AdminSite:
    """An admin panel for a set of SQLAlchemy models.

    Args:
        session_factory: The application's ``async_sessionmaker``. The admin uses it for every
            query, and the CLI (``oneadmin migrate``) uses its engine.
        secret_key: At least 32 characters of random data, loaded from the environment.
            Signs pagination cursors and derives CSRF tokens. Rotating it invalidates open
            cursors and CSRF tokens, not sessions. Optional in dev mode.
        title: Shown in the UI.
        auth_backend: Replace the built-in email/password login (e.g. for SSO). Default: the
            built-in backend with users created by ``oneadmin createsuperuser``.
        auth_settings: Session lifetimes and rate limits for the built-in backend.
        cookie_secure: Send the session cookie only over HTTPS. Keep it ``True``; browsers
            already treat ``http://localhost`` as secure. Set ``False`` only for local setups
            on another plain-HTTP host.
        conventions: Site-wide rules applied to every registered model before its own
            options (``oneadmin.conventions``): read-only or hidden fields by name,
            field types, labels, filters, and ``scope_by`` for multi-tenancy.
        trusted_origins: Extra full origins (``"https://admin.example.com"``) allowed through
            the CSRF origin check. Separate-host UIs also need CORS and suitable cookie settings
            configured by the host app; the bundled UI uses same-origin API requests.
        dev: Development mode, for trying OneAdmin locally with zero setup. Default: the
            ``ONEADMIN_DEV`` environment variable (``1``/``true``). In dev mode:

            - **only loopback peers are served**; other peers get 403
            - ``secret_key`` may be omitted, and cookies work over plain HTTP
            - OneAdmin's tables are migrated on the first request
            - while no admin user exists, the login page offers to create the first
              superuser with a token printed in the server log

            Bind to loopback and never enable it on a publicly reachable server or proxy.

    Example::

        admin = AdminSite(session_factory=async_session_maker, secret_key=settings.SECRET)
        admin.register(User)
        admin.mount(app, "/admin")
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        secret_key: str | None = None,
        title: str = "OneAdmin",
        auth_backend: AuthBackend | None = None,
        auth_settings: AuthSettings | None = None,
        cookie_secure: bool = True,
        trusted_origins: Collection[str] = (),
        conventions: Sequence[Convention] = (),
        dev: bool | None = None,
    ) -> None:
        self.dev = _env_flag(DEV_ENV_VAR) if dev is None else dev
        self.dev_setup_token = secrets.token_urlsafe(32) if self.dev else None
        if self.dev:
            log.warning(
                "oneadmin: DEVELOPMENT MODE. Only loopback peers are served; the "
                "first admin can be created from the login page with the setup token. "
                "Never expose this server or proxy publicly."
            )
            log.warning("oneadmin: First-run setup token: %s", self.dev_setup_token)
            secret_key = secret_key or DEV_SECRET_KEY
            cookie_secure = False
        if secret_key is None:
            raise ConfigurationError(
                "AdminSite(secret_key=...) is required (or dev=True for local trials). "
                "Generate one with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` "
                "and load it from the environment, never from source code."
            )
        if len(secret_key) < MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"AdminSite(secret_key=...) must be at least {MIN_SECRET_LENGTH} characters. "
                "Generate one with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` "
                "and load it from the environment, never from source code."
            )
        if not cookie_secure and not self.dev:
            log.warning(
                "oneadmin: cookie_secure=False sends the admin session cookie over plain HTTP. "
                "Never use this outside local development."
            )
        self.title = title
        self.session_factory = session_factory
        self.cookie_secure = cookie_secure
        self.trusted_origins = frozenset(trusted_origins)
        self.conventions: tuple[Convention, ...] = tuple(conventions)
        ids = [c.id for c in self.conventions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ConfigurationError(
                f"Two conventions share the id {duplicates}; pass id='...' to tell them apart."
            )
        self.auth = AuthService(session_factory, secret_key, auth_settings)
        """The built-in account service (users, sessions). Also used by the CLI."""
        self._session_backend = SessionCookieBackend(self.auth, cookie_name="oneadmin_session")
        self._auth_backend: AuthBackend = auth_backend or self._session_backend
        versions = RowVersioner(secret_key)
        self.service = ReadService(
            session_factory, CursorCodec(secret_key), self.admin_for, versions
        )
        self.writes = WriteService(self.service, versions, self.admins)
        self._middleware: list[Middleware] = []
        self.operations = OperationRunner(self._middleware)
        self._entries: list[list[Any]] = []
        self._auto: set[type[Any]] = set()
        """Models registered by ``register_all`` (an explicit ``register`` replaces them)."""
        self._admins: dict[str, ModelAdmin] = {}
        self._by_model: dict[type[Any], ModelAdmin] = {}
        self._app: FastAPI | None = None

    # ---- registration --------------------------------------------------------------------
    def register(
        self, model: type[Any], admin_class: type[ModelAdmin] | None = None
    ) -> Callable[[A], A]:
        """Register ``model``, directly or as a class decorator::

        admin.register(Tag)                       # defaults

        @admin.register(Post)                     # customised
        class PostAdmin(ModelAdmin):
            list_display = ("id", "title")
        """
        if self._app is not None:
            raise ConfigurationError("register() must be called before mount() / build_app()")
        if model in self._auto:  # an explicit registration replaces a register_all() one
            self._entries = [e for e in self._entries if e[0] is not model]
            self._auto.discard(model)
        entry: list[Any] = [model, admin_class or ModelAdmin]
        self._entries.append(entry)

        def decorator(cls: A) -> A:
            if not (isinstance(cls, type) and issubclass(cls, ModelAdmin)):
                raise ConfigurationError(
                    f"@register({model.__name__}) must decorate a ModelAdmin subclass"
                )
            entry[1] = cls
            return cls

        return decorator

    def register_all(
        self,
        models: Any,
        *,
        exclude: Iterable[type[Any]] = (),
        admin_class: type[ModelAdmin] | None = None,
    ) -> list[type[Any]]:
        """Register every model of a declarative base (or an iterable of models).

        Each model gets an admin built from ``oneadmin.core.autoconfig.suggest``: useful list
        columns, search on identifier-like text, filters on booleans/enums/timestamps, newest
        first. ``oneadmin init`` writes the same suggestions out as editable code.

        Skipped: models in ``exclude``, models already registered (so explicit
        ``@register`` classes win, whatever the call order), and single-table-inheritance
        subclasses (they share their parent's table). Returns the models registered here::

            admin.register_all(Base, exclude=[AuditTrail])
        """
        configure_mappers()  # relationships must resolve before suggestions are made
        skip = set(exclude) | {entry[0] for entry in self._entries}
        added: list[type[Any]] = []
        for model in _models_of(models):
            if model in skip:
                continue
            base = admin_class or ModelAdmin
            options = suggest(model).as_options()
            # Options the user's base class sets explicitly win over suggestions. (Only
            # classes below ModelAdmin count: ModelAdmin's own defaults are not choices.)
            chosen = {
                k
                for cls in base.__mro__
                if issubclass(cls, ModelAdmin) and cls is not ModelAdmin
                for k in vars(cls)
            }
            options = {k: v for k, v in options.items() if k not in chosen}
            self.register(model, type(f"{model.__name__}Admin", (base,), options))
            self._auto.add(model)
            added.append(model)
        return added

    def middleware(self, func: Middleware) -> Middleware:
        """Register operation middleware (a decorator); see ``oneadmin.core.operations``.

        The first registered is the outermost. Register before ``mount()``.
        """
        if self._app is not None:
            raise ConfigurationError("middleware() must be called before mount() / build_app()")
        self._middleware.append(func)
        self.operations = OperationRunner(self._middleware)
        return func

    # ---- lookups -------------------------------------------------------------------------
    def admins(self) -> list[ModelAdmin]:
        """All compiled admins, in registration order."""
        return list(self._admins.values())

    def admin_by_slug(self, slug: str) -> ModelAdmin | None:
        return self._admins.get(slug)

    def admin_for(self, model: type[Any]) -> ModelAdmin | None:
        """The primary (first registered) admin of ``model``, used for relation labels."""
        return self._by_model.get(model)

    @property
    def auth_backend(self) -> AuthBackend:
        return self._auth_backend

    @property
    def session_backend(self) -> SessionCookieBackend:
        """The built-in cookie backend (used for CSRF checks when it is the active backend)."""
        return self._session_backend

    @property
    def uses_builtin_auth(self) -> bool:
        return self._auth_backend is self._session_backend

    @property
    def engine(self) -> AsyncEngine:
        """The engine bound to ``session_factory`` (used by ``oneadmin migrate``)."""
        bind = self.session_factory.kw.get("bind")
        if not isinstance(bind, AsyncEngine):
            raise ConfigurationError(
                "AdminSite.session_factory must be bound to an AsyncEngine, e.g. "
                "async_sessionmaker(engine). Per-model binds aren't supported."
            )
        return bind

    # ---- ASGI ----------------------------------------------------------------------------
    def build_app(self) -> FastAPI:
        """Validate every registration and build the admin ASGI app. Idempotent.

        Raises ``ConfigurationError`` for any invalid ``ModelAdmin`` option, so mistakes
        surface at startup.
        """
        if self._app is not None:
            return self._app
        self._compile()
        app = FastAPI(
            title=f"{self.title} admin API", docs_url=None, redoc_url=None, openapi_url=None
        )
        errors.install(app)
        app.add_middleware(BodyLimitMiddleware)
        if self.dev:  # added first, so the security headers wrap its responses too
            app.add_middleware(DevModeMiddleware, prepare=self._dev_prepare)
        app.add_middleware(SecurityHeadersMiddleware)
        if self.uses_builtin_auth:
            app.include_router(build_auth_router(self, self._session_backend), prefix="/api/v1")
        app.include_router(build_router(self), prefix="/api/v1")
        mount_ui(app, title=self.title, builtin_auth=self.uses_builtin_auth, dev=self.dev)
        self._app = app
        return app

    async def _dev_prepare(self) -> None:
        """Dev mode: create or upgrade OneAdmin's tables before the first request."""
        await migrations.upgrade(self.engine)

    def mount(self, app: Any, path: str = "/admin") -> None:
        """Mount the admin into a FastAPI or Starlette application at ``path``."""
        if not path.startswith("/") or (path.endswith("/") and path != "/"):
            raise ConfigurationError(
                f"mount path {path!r} must start with '/' and not end with '/'"
            )
        app.mount(path, self.build_app(), name=f"oneadmin:{path}")

    def openapi(self) -> dict[str, Any]:
        """The admin API's OpenAPI document (source for the frontend's generated types)."""
        return self.build_app().openapi()

    def _compile(self) -> None:
        configure_mappers()  # resolve string relationships before introspection
        for model, admin_cls in self._entries:
            admin = admin_cls()
            slug = admin.compile(model, self.conventions).slug
            if slug in self._admins:
                raise ConfigurationError(
                    f"Two admins use the slug {slug!r}; set `name = ...` on one of them."
                )
            self._admins[slug] = admin
            self._by_model.setdefault(model, admin)


def _models_of(source: Any) -> list[type[Any]]:
    """Mapped classes of a declarative base / registry, or of an iterable of classes."""
    registry = getattr(source, "registry", source)
    mappers = getattr(registry, "mappers", None)
    if mappers is None:
        models = list(source)
    else:
        models = [
            m.class_
            for m in mappers
            # single-table inheritance: same table as the parent -> one admin for the table
            if not (m.inherits is not None and m.local_table is m.inherits.local_table)
        ]
    for model in models:
        if not isinstance(model, type):
            raise ConfigurationError(f"register_all(): {model!r} is not a mapped class")
    return sorted(models, key=lambda m: (m.__module__, m.__qualname__))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
