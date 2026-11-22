"""``/api/v1/auth/*``: login, logout and session introspection for the built-in backend.

No ``from __future__ import annotations``: FastAPI must evaluate the local ``Annotated``
dependency aliases at definition time (see ``router.py``).
"""

import asyncio
import secrets
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from oneadmin.api.errors import ApiError
from oneadmin.api.guards import CSRF_HEADER, json_body, same_origin
from oneadmin.auth.backend import AdminIdentity, SessionCookieBackend
from oneadmin.auth.passwords import WeakPassword
from oneadmin.auth.service import InvalidCredentials, InvalidEmail, RateLimited

if TYPE_CHECKING:
    from oneadmin.site import AdminSite


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class SetupIn(LoginIn):
    setup_token: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    email: str
    is_superuser: bool


class SetupStatus(BaseModel):
    needed: bool
    """True in dev mode while no admin user exists: the UI offers to create the first one."""


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    """Send back as the ``X-CSRF-Token`` header on every state-changing request."""


def _user(identity: AdminIdentity) -> UserOut:
    return UserOut(id=identity.id, email=identity.email, is_superuser=identity.is_superuser)


def build_auth_router(site: "AdminSite", backend: SessionCookieBackend) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])
    service = backend.service

    def guard_unsafe(request: Request) -> None:
        same_origin(request, site.trusted_origins)
        json_body(request)

    def cookie_path(request: Request) -> str:
        return request.scope.get("root_path", "").rstrip("/") or "/"

    def set_session_cookie(request: Request, response: Response, token: str) -> None:
        response.set_cookie(
            backend.cookie_name,
            token,
            max_age=int(service.settings.absolute_timeout.total_seconds()),
            path=cookie_path(request),
            secure=site.cookie_secure,
            httponly=True,
            samesite="lax",
        )

    @router.post(
        "/login",
        response_model=SessionOut,
        dependencies=[Depends(guard_unsafe)],
        responses={429: {"description": "Too many failed attempts; see Retry-After"}},
    )
    async def login(body: LoginIn, request: Request, response: Response) -> SessionOut:
        try:
            result = await service.login(
                body.email,
                body.password,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        except RateLimited as exc:
            raise ApiError(
                429, "rate_limited", str(exc), headers={"Retry-After": str(exc.retry_after)}
            ) from None
        except InvalidCredentials:
            raise ApiError(401, "invalid_credentials", "Invalid email or password.") from None
        # A session cookie the client already had is simply replaced: login always issues a
        # fresh token, so an attacker-planted cookie can't be "upgraded" (session fixation).
        set_session_cookie(request, response, result.token)
        return SessionOut(user=_user(result.identity), csrf_token=result.csrf_token)

    setup_lock = asyncio.Lock()

    async def setup_needed() -> bool:
        return site.dev and await service.count_users() == 0

    @router.get("/setup", response_model=SetupStatus)
    async def setup_status() -> SetupStatus:
        """Whether first-run setup is available (dev mode, no admin user yet)."""
        return SetupStatus(needed=await setup_needed())

    @router.post(
        "/setup",
        response_model=SessionOut,
        dependencies=[Depends(guard_unsafe)],
        responses={409: {"description": "An admin user already exists"}},
    )
    async def setup(body: SetupIn, request: Request, response: Response) -> SessionOut:
        """Dev mode only: create the first superuser and sign in as them.

        Refused (409) as soon as any admin user exists. The lock serialises concurrent
        attempts in this process; dev mode is a single local process by design.
        """
        if not site.dev:
            raise ApiError(404, "not_found", "Not found.")
        if not secrets.compare_digest(body.setup_token, site.dev_setup_token or ""):
            raise ApiError(403, "invalid_setup_token", "Invalid first-run setup token.")
        async with setup_lock:
            if not await setup_needed():
                raise ApiError(409, "setup_done", "An admin user already exists. Sign in instead.")
            try:
                await service.create_user(body.email, body.password, is_superuser=True)
            except (InvalidEmail, WeakPassword) as exc:
                param = "email" if isinstance(exc, InvalidEmail) else "password"
                raise ApiError(400, "invalid_setup", str(exc), param) from None
        result = await service.login(body.email, body.password, ip=None)
        set_session_cookie(request, response, result.token)
        return SessionOut(user=_user(result.identity), csrf_token=result.csrf_token)

    @router.get("/session", response_model=SessionOut)
    async def current_session(request: Request) -> SessionOut:
        token = backend.token(request)
        identity = await service.resolve(token)
        if token is None or identity is None:
            raise ApiError(401, "not_authenticated", "Log in to use the admin.")
        return SessionOut(user=_user(identity), csrf_token=service.csrf_token(token))

    @router.post("/logout", status_code=204, dependencies=[Depends(guard_unsafe)])
    async def logout(request: Request) -> Response:
        token = backend.token(request)
        if token is not None:
            if not service.check_csrf(token, request.headers.get(CSRF_HEADER)):
                raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token.")
            await service.logout(token)
        response = Response(status_code=204)
        response.delete_cookie(
            backend.cookie_name, path=cookie_path(request), secure=site.cookie_secure, httponly=True
        )
        return response

    return router
