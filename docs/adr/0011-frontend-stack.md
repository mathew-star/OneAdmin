# 0011: Frontend stack

- Status: accepted
- Date: 2026-11-06

## Context
The budget is ≤150 KB gzip initial JS, and a solo maintainer has to keep it working. Versions verified on npm 2026-11-06.

## Decision
| Layer | Choice | Notes |
|---|---|---|
| Framework | React 19, TypeScript strict | |
| Build | Vite 8 | relative `base: "./"` |
| Routing | TanStack Router (code-based routes, `basepath` from injected config) | typed search params, so URL = state |
| Data | TanStack Query | cache and dedup; the ETag-aware schema query |
| Table | **No TanStack Table in v1.** A semantic `<table>` component driven by the server | Sorting, filtering and paging are server-side, so a headless table library adds weight and little value; v9 is also very new. `@tanstack/react-virtual` is used only in infinite-scroll mode above 200 rendered rows (virtualising 50 rows hurts a11y and Ctrl+F). |
| Forms | small in-house form state + server-side Pydantic errors | no client-side schema duplication; revisit TanStack Form if forms grow |
| UI primitives | `radix-ui` (dialog, popover, dropdown, select, tooltip) + Tailwind CSS 4 with a custom token set (not a template look); `cmdk` for the command palette | |
| Heavy widgets | CodeMirror 6 JSON, lazy-loaded (not Monaco, which is ~2 MB) | |
| API types | openapi-typescript (types only) | |
| Tooling | Biome, Vitest, Playwright, size-limit | |

## Consequences
We own table and form code, which keeps it small and accessible.

## Revisit when
Client-side column features (resizing, pinning, reordering) are requested. TanStack Table is the candidate then.
