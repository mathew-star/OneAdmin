"""Error contract: every error response is ``{"error": {"code", "message", "param"}}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from oneadmin.auth.service import AdminNotMigrated
from oneadmin.core.errors import Conflict, QueryError, ValidationError, WriteError


class ApiError(Exception):
    """An error with a stable machine-readable ``code`` and a human-readable ``message``."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        param: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.param = status, code, message, param
        self.headers = headers


#: HTTP status of each ``WriteError`` code (ADR-0018).
WRITE_STATUS: dict[str, int] = {
    "validation_failed": 400,
    "forbidden": 403,
    "out_of_scope": 403,
    "not_found": 404,
    "unknown_action": 404,
    "conflict": 409,
    "integrity_error": 409,
    "precondition_required": 428,
}


def problem(
    status: int,
    code: str,
    message: str,
    param: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "param": param, **extra}
    return JSONResponse({"error": body}, status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.message, exc.param, exc.headers)

    @app.exception_handler(AdminNotMigrated)
    async def _not_migrated(_: Request, exc: AdminNotMigrated) -> JSONResponse:
        return problem(503, "admin_not_migrated", str(exc))

    @app.exception_handler(QueryError)
    async def _query(_: Request, exc: QueryError) -> JSONResponse:
        return problem(400, exc.code, exc.message, exc.param)

    @app.exception_handler(WriteError)
    async def _write(_: Request, exc: WriteError) -> JSONResponse:
        extra: dict[str, Any] = {}
        if isinstance(exc, ValidationError):
            extra["fields"] = exc.errors
        if isinstance(exc, Conflict) and exc.current is not None:
            row = exc.current
            extra["current"] = {"pk": row.pk, "values": row.values, "version": row.version}
        status = WRITE_STATUS.get(exc.code, 400)
        return problem(status, exc.code, exc.message, exc.param, **extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ())[1:]) or None
        return problem(400, "invalid_request", str(first.get("msg", "invalid request")), loc)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return problem(exc.status_code, code, str(exc.detail))
