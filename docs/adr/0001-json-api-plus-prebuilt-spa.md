# 0001: JSON API + prebuilt SPA shipped in the wheel

- Status: accepted
- Date: 2026-11-06

## Context
The two incumbents, sqladmin and Starlette-Admin, render on the server with Jinja. Their real pain points are query strategy and missing features, not SSR itself (landscape.md). Users must never need Node.

## Options considered
1. **Jinja SSR + htmx.** Simple, with no JS build. But interactions such as inline filters, keyboard nav and optimistic UI are harder, and it is hard to stand out from sqladmin.
2. **Prebuilt SPA + versioned JSON API.** The proven model (FastAdmin, Piccolo Admin). It has a clean contract, the same API is usable by scripts, and the UX can be rich.
3. **Users write the frontend (React-Admin style).** Contradicts "no per-model frontend code".

## Decision
Option 2. The API is a product in its own right (`/api/v1`), documented via OpenAPI.

## Consequences
- We now own a frontend toolchain and a supply chain (mitigated by budgets, lockfile, audits).
- The contract needs versioning (ADR-0008).
- Extensibility is server-side only in v1 (no JS plugins).

## Revisit when
Users ask for custom widgets often enough to justify a plugin ABI (module federation or web components).
