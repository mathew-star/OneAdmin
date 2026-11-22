# 0017: SQLAlchemy-first, adapter-ready

- Status: accepted (owner said "continue" on the recommendation, 2026-11-06). Refines ADR-0002.
- Date: 2026-11-06

## Context
The owner asked whether OneAdmin could work with any ORM. Multi-ORM admins end up with lowest-common-denominator features, and per-ORM security guarantees (tenant scoping, same-transaction audit) must be re-proven per backend.

## Decision
- v1 ships one backend: SQLAlchemy 2.x async.
- The seam is the **service layer**: `oneadmin.api` (HTTP) and the UI depend only on ORM-neutral results (rows as wire-safe dicts, pages, counts, the schema contract). A layering test forbids `oneadmin.api` from importing `sqlalchemy`.
- `ModelAdmin` hooks (`get_queryset(ctx, stmt)`) are SQLAlchemy-native by design. A future adapter would ship its own `ModelAdmin` flavour.
- A second adapter is built only on clear demand, as a separate package that must pass a shared conformance suite (pagination walks, scoping, security). The `DataBackend` protocol is extracted from the SQLAlchemy service at that point, not speculatively now.

## Consequences
- No promise of "any ORM" in v1 docs.
- Extraction cost later is bounded because HTTP/UI never see SQLAlchemy types.
