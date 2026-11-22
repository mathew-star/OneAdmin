# 0007: Supported versions policy

- Status: proposed (product decision; confirm with owner)
- Date: 2026-11-06

## Context
- SQLAlchemy 2.1 and Starlette 1.x require Python ≥ 3.11.
- CPython 3.10 reached EOL in October 2026.
- Today is 2026-11-06.

## Decision
| Dependency | Supported versions |
|---|---|
| Python | **3.11–3.14**, following CPython's support window (each version dropped within 6 months of EOL) |
| SQLAlchemy | `>=2.0.36,<2.2` (lowered from 2.0.40 for the pilot, see ADR-0015; tested on 2.0.36) (CI covers 2.0.x latest and 2.1.x latest) |
| Pydantic | `>=2.10,<3` |
| FastAPI | `>=0.115` |
| PostgreSQL | 14–18 |

## Consequences
3.10 users are excluded. That is acceptable: 3.10 is EOL and the upstream stack has moved on.

## Revisit when
Each CPython release or EOL.
