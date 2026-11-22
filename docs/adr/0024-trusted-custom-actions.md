# ADR-0024: Treat custom actions as trusted application code

## Context

Custom `ModelAdmin` actions receive selected, scoped rows and the request's raw SQLAlchemy session. That session can also update unselected rows, other models, or issue direct SQL. OneAdmin cannot promise to scope or audit arbitrary database effects of developer code through this API.

## Options

- Attempt to inspect ORM dirty state after the callback. Autoflush and direct SQL can write before inspection, so this would not enforce the boundary.
- Hide the raw session behind a restricted API. This requires a new action contract, a migration path, and a way to express multi-model work.
- State the trust boundary explicitly and make the selected-row guarantees precise.

## Decision

Custom actions are trusted application code. OneAdmin checks permission and scope for the selected rows before invoking an action and checks/audits those rows and newly added rows of its registered model afterward. The action author owns authorization, tenancy, and audit coverage for all other writes. The user guide and `AdminContext.session` documentation state this explicitly.

## Consequences

Custom actions remain powerful, but a library user must review them like application service code. OneAdmin will not claim that `scope_by` or its audit log covers arbitrary statements through `ctx.session`. Before declaring the public API stable, evaluate a constrained action API that can enforce broader guarantees without blocking legitimate multi-model operations.

## Revisit when

Revisit before a stable release or when a concrete custom-action security incident demonstrates that the raw session contract is too easy to misuse.
