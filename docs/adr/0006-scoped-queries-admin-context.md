# 0006: Scoped queries and `AdminContext` (tenancy and authorization)

- Status: accepted
- Date: 2026-11-06

## Context
Tenancy enforced only on list queries is the classic IDOR. sqladmin hooks lack the session (#925). The draft reads `request.state.user` implicitly.

## Decision
- A typed, frozen `AdminContext(user, permissions, tenant, request, session)` is passed explicitly to **every** hook (`get_queryset`, `has_*_permission`, `before_save`, `after_save`, actions).
- **One scoped builder.** Every read (list, detail, autocomplete, FK labels, export, actions, the update/delete target lookup) starts from `admin.get_queryset(ctx, select(...))`. Writes load their target through the scoped query (`WHERE pk = :pk AND <scope>`), never through `session.get()`.
- An unscoped primary-key fetch is not reachable from the API layer. A security test parametrises every endpoint with a foreign-tenant PK and expects 404, not 403, so existence is not revealed.
- A **related-model scope**: FK autocomplete and label joins apply the *target* model's admin `get_queryset`.

## Consequences
- Slight overhead: scope predicates on every query (they should be indexed, and `oneadmin check` warns when they aren't).
- Users who forget a scope on one model get it consistently wrong, not inconsistently wrong. That is easier to audit.

## Revisit when
Row-level security (PG RLS) integration is requested. It would be complementary (`SET LOCAL app.tenant_id`).
