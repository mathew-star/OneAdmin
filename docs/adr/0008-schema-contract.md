# 0008: UI schema contract and TS type generation

- Status: accepted
- Date: 2026-11-06

## Context
The frontend and backend drift apart unless one side is generated from the other. Orval-style clients are heavy.

## Decision
- Pydantic models in `oneadmin/api/contract.py` are the **single source of truth** for `/api/v1/schema` and all API payloads.
- The schema payload carries `contract_version: int` (starts at 1). Additive changes keep the version; breaking changes bump it. The SPA refuses to run on a mismatch, with a clear message.
- The OpenAPI document is exported by `oneadmin schema --openapi`. **openapi-typescript** generates `frontend/src/api/types.gen.ts` (types only), consumed by a tiny typed fetch wrapper. CI regenerates it and fails on diff.
- Snapshot tests are kept for the OpenAPI document and for the schema JSON of the example app.
- Field "widgets" are a closed enum in the contract. Unknown types map to `readonly`.

## Consequences
- Every contract change touches Python, a regenerated TS file and a snapshot update. That is intentional friction.

## Revisit when
Never for the principle. The tooling may change.
