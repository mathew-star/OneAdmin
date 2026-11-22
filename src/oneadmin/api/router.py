"""``/api/v1`` model endpoints: schema, reads, writes, actions and history.

No ``from __future__ import annotations`` here: FastAPI must evaluate the locally defined
``Annotated[..., Depends(...)]`` aliases at definition time.

Access rules (ADR-0006, ADR-0019):
- Not signed in → 401.
- A model the user can't view → 404 ``unknown_model``: it is indistinguishable from a model
  that isn't registered.
- A write the user may not make on a model they can view → 403 ``forbidden``.
- Every write passes the CSRF guards (``guard_write``) before anything else happens.
"""

import hashlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response

from oneadmin.api.contract import (
    CONTRACT_VERSION,
    ActionIn,
    ActionOut,
    CountOut,
    HistoryEntry,
    HistoryOut,
    ListOut,
    Problem,
    RowOut,
    SiteSchema,
    for_viewer,
    model_schema,
)
from oneadmin.api.errors import ApiError
from oneadmin.api.guards import CSRF_HEADER, json_body, same_origin
from oneadmin.core.context import AdminContext
from oneadmin.core.model_admin import ModelAdmin
from oneadmin.core.operations import Operation
from oneadmin.core.service import ListParams, WireRow

if TYPE_CHECKING:
    from oneadmin.site import AdminSite

_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": Problem},
    401: {"model": Problem},
    403: {"model": Problem},
    404: {"model": Problem},
}
_WRITE_ERRORS: dict[int | str, dict[str, object]] = {
    **_ERRORS,
    409: {"model": Problem, "description": "Version conflict or constraint violation"},
    428: {"model": Problem, "description": "If-Match with the row's version is required"},
}


def row_out(row: WireRow) -> RowOut:
    return RowOut(pk=row.pk, values=row.values, version=row.version)


def build_router(site: "AdminSite") -> APIRouter:
    router = APIRouter(responses=_ERRORS)
    slug_for = {a.model: a.compiled.slug for a in site.admins()}
    bases = {a.compiled.slug: model_schema(a, slug_for) for a in site.admins()}

    run = site.operations.run  # every model operation goes through the middleware chain

    # ---- dependencies --------------------------------------------------------------------
    async def context(request: Request) -> AsyncIterator[AdminContext]:
        identity = await site.auth_backend.authenticate(request)
        if identity is None:
            raise ApiError(401, "not_authenticated", "Log in to use the admin.")
        async with site.session_factory() as session:
            yield AdminContext(identity=identity, session=session, request=request)

    Ctx = Annotated[AdminContext, Depends(context)]

    async def model_admin(slug: str, ctx: Ctx) -> ModelAdmin:
        admin = site.admin_by_slug(slug)
        if admin is None or not await admin.has_view_permission(ctx):
            raise ApiError(404, "unknown_model", f"No model {slug!r} is registered.")
        return admin

    Admin = Annotated[ModelAdmin, Depends(model_admin)]

    def guard_write(request: Request, _: Ctx) -> None:
        """CSRF defences for every state-changing request (threat model T1)."""
        same_origin(request, site.trusted_origins)
        if request.method != "DELETE":  # HTML forms can't send DELETE at all
            json_body(request)
        if site.uses_builtin_auth:
            token = site.session_backend.token(request)
            if token is None or not site.auth.check_csrf(token, request.headers.get(CSRF_HEADER)):
                raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token.")

    Guarded = Depends(guard_write)

    def list_params(
        request: Request,
        sort: str | None = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        limit: Annotated[int | None, Query(ge=1, le=500)] = None,
        last: bool = False,
        count: bool = True,
    ) -> ListParams:
        filters = [(k, v) for k, v in request.query_params.multi_items() if k.startswith("f.")]
        return ListParams(sort, q, filters, cursor, limit, last, count)

    Params = Annotated[ListParams, Depends(list_params)]
    IfMatch = Annotated[str | None, Header(alias="If-Match", max_length=200)]

    # ---- schema --------------------------------------------------------------------------
    @router.get("/schema", response_model=SiteSchema)
    async def get_schema(request: Request, ctx: Ctx) -> Response:
        """The models this user can see, with their permissions and actions."""
        models = [
            await for_viewer(bases[a.compiled.slug], a, ctx)
            for a in site.admins()
            if await a.has_view_permission(ctx)
        ]
        body = SiteSchema(
            contract_version=CONTRACT_VERSION, title=site.title, models=models
        ).model_dump_json()
        etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/json", headers=headers)

    # ---- reads ---------------------------------------------------------------------------
    @router.get("/models/{slug}/rows", response_model=ListOut)
    async def list_rows(ctx: Ctx, admin: Admin, params: Params) -> ListOut:
        result = await run(
            Operation("list", admin, ctx, params=params),
            lambda: site.service.list(ctx, admin, params),
        )
        return ListOut(
            rows=[row_out(r) for r in result.rows],
            next_cursor=result.next_cursor,
            prev_cursor=result.prev_cursor,
            pagination=result.mode,
            count=None
            if result.count is None
            else CountOut(
                value=result.count.value, exact=result.count.exact, method=result.count.method
            ),
        )

    @router.get("/models/{slug}/count", response_model=CountOut)
    async def count_rows(ctx: Ctx, admin: Admin, params: Params) -> CountOut:
        """Exact count on demand (the list endpoint returns a cheap one)."""
        c = await run(
            Operation("count", admin, ctx, params=params),
            lambda: site.service.count(ctx, admin, params),
        )
        return CountOut(value=c.value, exact=c.exact, method=c.method)

    @router.get("/models/{slug}/rows/{pk}", response_model=RowOut)
    async def get_row(ctx: Ctx, admin: Admin, pk: str, response: Response) -> RowOut:
        row = await run(
            Operation("get", admin, ctx, pk=pk), lambda: site.service.get(ctx, admin, pk)
        )
        if row is None:
            raise ApiError(404, "not_found", "Row not found.")
        response.headers["ETag"] = f'"{row.version}"'
        return row_out(row)

    @router.get("/models/{slug}/rows/{pk}/history", response_model=HistoryOut)
    async def row_history(
        ctx: Ctx, admin: Admin, pk: str, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> HistoryOut:
        """Audit entries of one row, newest first."""
        entries = await run(
            Operation("history", admin, ctx, pk=pk),
            lambda: site.writes.history(ctx, admin, pk, limit=limit),
        )
        if entries is None:
            raise ApiError(404, "not_found", "Row not found.")
        return HistoryOut(
            entries=[
                HistoryEntry(
                    id=e.id,
                    at=e.at,
                    actor_id=e.actor_id,
                    actor_email=e.actor_email,
                    action=e.action,
                    changes=e.changes,
                )
                for e in entries
            ]
        )

    # ---- writes --------------------------------------------------------------------------
    @router.post(
        "/models/{slug}/rows",
        status_code=201,
        response_model=RowOut,
        responses=_WRITE_ERRORS,
        dependencies=[Guarded],
    )
    async def create_row(
        ctx: Ctx, admin: Admin, payload: Annotated[dict[str, Any], Body()], response: Response
    ) -> RowOut:
        if not await admin.has_add_permission(ctx):
            raise ApiError(403, "forbidden", "You don't have permission to add rows here.")
        row = await run(
            Operation("create", admin, ctx, payload=payload),
            lambda: site.writes.create(ctx, admin, payload),
        )
        response.headers["ETag"] = f'"{row.version}"'
        return row_out(row)

    @router.patch(
        "/models/{slug}/rows/{pk}",
        response_model=RowOut,
        responses=_WRITE_ERRORS,
        dependencies=[Guarded],
    )
    async def update_row(
        ctx: Ctx,
        admin: Admin,
        pk: str,
        payload: Annotated[dict[str, Any], Body()],
        response: Response,
        if_match: IfMatch = None,
    ) -> RowOut:
        """Change the given fields only. Requires ``If-Match: <version>``."""
        if not await admin.has_change_permission(ctx):
            raise ApiError(403, "forbidden", "You don't have permission to change rows here.")
        row = await run(
            Operation("update", admin, ctx, pk=pk, payload=payload),
            lambda: site.writes.update(ctx, admin, pk, payload, if_match),
        )
        response.headers["ETag"] = f'"{row.version}"'
        return row_out(row)

    @router.delete(
        "/models/{slug}/rows/{pk}",
        status_code=204,
        responses=_WRITE_ERRORS,
        dependencies=[Guarded],
    )
    async def delete_row(ctx: Ctx, admin: Admin, pk: str, if_match: IfMatch = None) -> Response:
        """Requires ``If-Match: <version>``."""
        if not await admin.has_delete_permission(ctx):
            raise ApiError(403, "forbidden", "You don't have permission to delete rows here.")
        await run(
            Operation("delete", admin, ctx, pk=pk),
            lambda: site.writes.delete(ctx, admin, pk, if_match),
        )
        return Response(status_code=204)

    @router.post(
        "/models/{slug}/actions/{name}",
        response_model=ActionOut,
        responses=_WRITE_ERRORS,
        dependencies=[Guarded],
    )
    async def run_action(ctx: Ctx, admin: Admin, name: str, body: ActionIn) -> ActionOut:
        """Run a bulk action on the selected rows: all of them, or none."""
        result = await run(
            Operation("action", admin, ctx, pks=tuple(body.pks), action=name),
            lambda: site.writes.run_action(ctx, admin, name, body.pks),
        )
        return ActionOut(count=result.count, message=result.message)

    return router
