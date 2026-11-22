# 0002: SQLAlchemy-only, async-only, PostgreSQL-first

- Status: accepted
- Date: 2026-11-06

## Context
Multi-ORM admins (FastAdmin, Starlette-Admin) end up with lowest-common-denominator features. Our differentiators (keyset plans, estimates, loader strategies) need deep, dialect-aware SQLAlchemy. I am a solo maintainer.

## Options considered
- Multi-ORM adapters.
- SQLAlchemy sync and async.
- **SQLAlchemy async only, with dialect tiers.**

## Decision
SQLAlchemy 2.x async only (`AsyncSession` / `async_sessionmaker`). Dialect tiers:
- **Tier 1 (fully tested):** PostgreSQL 14–18.
- **Tier 2 (tested):** SQLite via aiosqlite, for dev and tests. No estimated counts.
- **Tier 3 (best-effort):** MySQL/MariaDB.

## Consequences
- Sync-SQLAlchemy users are excluded.
- The CI matrix stays small.
- Dialect-specific code lives behind a `Dialect` strategy object in `core/query/dialects.py`.

## Revisit when
Evidence of MySQL demand (issues or upvotes), or a contributor who is willing to own it.
