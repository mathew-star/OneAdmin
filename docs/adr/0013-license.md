# 0013: License

- Status: **proposed. Owner decision required**
- Date: 2026-11-06

## Options
- **MIT:** maximum adoption; matches Starlette-Admin, FastAdmin and Piccolo.
- **BSD-3:** like sqladmin and Django; adds a no-endorsement clause.
- **Apache-2.0:** explicit patent grant; slightly more friction.
- A copyleft or source-available license would hurt adoption of a library.

## Recommendation
**MIT**, for ecosystem consistency and the lowest adoption friction. Frontend dependencies are all MIT or ISC. We will ship a THIRD_PARTY_NOTICES file generated at build time for the bundled JS.
