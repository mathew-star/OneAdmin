# M4: Minimal UI (read-only)

ADR-0011 (frontend stack), technical-findings §7 (serving under any prefix).

## Goal
`admin.mount(app, "/admin")` in a host app, and then `http://host/admin/` in a browser works:
- sign in
- browse every registered model
- sort, filter, search and page through millions of rows
- open a row

Read-only: editing is M5/M6.

## Design
- **The URL is the state.**
  - The list's sort, search, filters and cursor live in the query string. Reload, back/forward and copy-link all work.
  - Search params map one-to-one onto the API's: `sort`, `q`, `f.<field>__<op>`, `cursor`, `last`. Nothing is invented on the client.
- **Routes** (code-based TanStack Router, `basepath` from the injected config):

  | Route | Shows |
  |---|---|
  | `/login` | sign-in form |
  | `/` | model index |
  | `/m/$slug` | list |
  | `/m/$slug/r/$pk` | detail |
- **The server is the source of truth for behaviour.**
  - The UI reads `/schema` and only offers what the server allows: sortable columns, filter operators per field, search box, last-page link only in keyset mode.
  - Labels, kinds and nullability come from the schema.
- **Errors:** every failed API call becomes an `ApiError` with the server's code, message and param.
  - 401 → login with `?next=` (only same-app paths are accepted).
  - 400 on a list → message shown inline, with a "Reset view" link.
  - 503 `admin_not_migrated` → instructions.
- **CSRF:**
  - The token comes from `/auth/login` and `/auth/session`.
  - The API client sends it as `X-CSRF-Token` on every unsafe method, and refuses to send an unsafe request without one.
- **CSP stays strict** (`script-src 'self'; style-src 'self'`). No inline scripts or styles in the build, and the config comes from the inert JSON block. A test asserts the built `index.html` has no inline script or style.
- **Counts:**
  - estimate → "≈ 1.2M"
  - capped → "10,000+"
  - exact → "1,234"
  - Non-exact counts get a "Count exactly" button (`/count`).
  - Counts never block the rows.
- **Values by kind** (one `formatValue` module, unit-tested):
  - booleans: icon with text
  - null: "—" (with a screen-reader label)
  - datetimes: shown in the viewer's locale when tz-aware, naive ones as stored
  - decimals and big integers: kept as strings
  - JSON: truncated monospace
  - relations: label linking to the target row, when the target is registered
- **API types** are generated, never hand-written:
  1. `scripts/export_openapi.py` writes `frontend/openapi.json`; a pytest test fails if it is stale.
  2. `pnpm gen:api` turns it into `src/api/openapi.d.ts`; `pnpm check:api` fails if that is stale.
- **Look:**
  - a dense, calm, neutral design built on a small token set (CSS variables), light and dark following the OS
  - not a template look: data first, one accent colour, tabular figures for numbers
- **Accessibility:**
  - semantic `<table>` with `aria-sort`, labelled controls, visible focus
  - skip link, a live region for loading/count updates
  - full keyboard use
  - axe clean in the e2e test

## Tasks
1. Scaffold `frontend/`:
   - Vite 8, React 19, TS strict, Tailwind 4, TanStack Router + Query, `radix-ui`, `lucide-react`
   - Biome, Vitest (+ Testing Library, happy-dom)
   - Vite `base: "./"`; dev server under `/admin/` with `/admin/api` proxied to `:8000`
2. `scripts/export_openapi.py` + staleness test; `openapi.json` → `openapi.d.ts`.
3. API client (`src/api/`): fetch wrapper, `ApiError`, CSRF, query keys and hooks.
4. App shell: config bootstrap, router, auth gate, sidebar navigation (collapsible on narrow screens), user menu with sign-out.
5. Login page: errors for invalid credentials and rate limiting (with retry time).
6. List page: columns from `list_display`, sortable headers, search (debounced), filter bar, cursor pager (first/prev/next/last), count, empty and error states.
7. Detail page: all fields, relations linked, back to the list keeping its state.
8. Build checks:
   - `scripts/check-bundle.mjs` enforces ≤150 KB gzip of initial JS and no inline script/style in `dist/index.html`
   - the hatch hook builds it into the wheel, and `check_wheel.py` asserts real assets
9. Python test: the served `index.html` has `<base href>` + config for any mount prefix and the hashed assets resolve.
10. Playwright smoke test against a real app (PG + seeded data):
    - login → list → sort → filter → page → detail → logout
    - axe on each page
11. Docs:
    - guide page "Using the admin UI" and frontend development notes in `frontend/README.md`
    - JOURNAL, CHANGELOG, pilot log

## Acceptance
- `pnpm build && pnpm test && pnpm lint && pnpm check:api` pass; bundle ≤150 KB gzip.
- `uv build` produces a wheel containing the real UI; a clean venv serves it.
- In `backend/` (pilot): the full flow works in a real browser at `/admin/`, with no CSP violations in the console.
- The Playwright smoke test and axe pass.
