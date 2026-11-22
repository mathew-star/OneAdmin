# OneAdmin roadmap: from working to the admin people pick first

Written 2026-11-06, after M0–M6 (a working, pilot-tested admin).

`docs/PLAN.md` §3 records what has been built. This document is the plan from here to 1.0. It is a living plan: each phase starts with a milestone doc (`docs/milestones/NN-*.md`), and every reversal of a v1 non-goal gets an ADR.

---

## 1. Why people would switch

People choose an admin panel in their first ten minutes:
1. How fast is it to get running?
2. Does it look and feel good?
3. Does it have what I need today?

Only *after* that do speed, safety and the audit log matter. Today OneAdmin wins on the second group and loses the first ten minutes:
- there's no PyPI release, auto-registration or demo
- inlines, export and uploads are missing
- configuration is shallow compared with Django

**Positioning to earn:**

> **The FastAPI admin that's running in 5 minutes, configurable like Django's, stays fast at 10 million rows, and lets you undo anything.**

Each clause maps to a phase below, and each comes with a number we publish and keep honest in CI.

## 2. Engineering principles (they hold for every phase)

1. **Configure in Python, compile at startup, render in the browser.**
   - Everything is declared server-side.
   - It resolves at boot into one immutable description of the admin, compiled the way a compiler produces its internal representation.
   - The SPA renders a fixed, versioned set of building blocks.
   - Customisation costs nothing per request.
2. **Customisation cannot break the guarantees.**
   - Scoping (`get_queryset`), keyset paging, per-row permissions, transactions and the audit log sit *inside* every extension point, never beside it.
   - A plugin can add behaviour; it cannot bypass the core.
3. **One pattern everywhere:** a Python spec, a registry, and a renderer key. Learn it once for fields, and it works for widgets, filters, actions, pages and layouts.
4. **Overrides never require copying.** Change one field's widget without rewriting the form. Django's template overrides fail this test.
5. **Progressive disclosure.** Every layer (zero config → options → hooks → components → layout → conventions → replace a subsystem) is optional. The simple case never gets harder.
6. **Every public extension point is typed, documented, contract-tested and versioned.** Adding one is an ADR, because it is forever.
7. **Prove every claim.**
   - Benchmarks, bundle size, query counts and the accessibility audit run in CI.
   - Marketing numbers come from the repo.
   - No telemetry, ever. Adoption is measured from public signals.

## 3. Phases

The sizes assume the current pace (one maintainer working with an AI pair). They are relative estimates, not commitments.

### Phase 0: Ground truth (S, ~1 week)
**Goal:** stop building on assumptions.

**Tasks**
- The owner's hands-on pilot pass on `backend/`; findings go into `docs/pilot/`.
- Push to a GitHub remote, and run CI for the first time (lint, types, PG 14/17/18 × SA 2.0/2.1, frontend, e2e, build).
- Decide the license (MIT is recommended, ADR-0013).
- A versioning and deprecation policy: SemVer, `0.x` minors may break with a documented migration.
- Recruit 3–5 outside trial users (FastAPI Discord or Reddit, colleagues). Ask what blocks them, and reorder Phases 2–4 with the answers.

**Exit:** CI green on every matrix cell; pilot report written; at least 3 trial users booked.

### Phase 1: The extensibility core (L, ~3–4 weeks) — **M7** ✓ (2026-11-07)
**Goal:** settle the public API shape *before* 0.1, so early adopters don't pay for later breaking changes.

**Tasks**
1. **One definition per field type (`FieldType`).**
   - Today the rules for a kind are spread over `coerce`, `wire`, `write_spec`, `filters` and the frontend's `format`/`formValues`.
   - Unify into one protocol per type: `to_wire`, `from_wire`, filter operators and SQL, sortability, display, widget key.
   - Add a registry with matching rules (`admin.fields.register(MoneyField, when=...)`).
   - The frontend gets the matching widget/cell registry, keyed by the renderer key.
2. **Configuration compiler with provenance.**
   - `CompiledAdmin` becomes a full description of the admin, built by ordered passes: introspection → defaults → site conventions → options → validation.
   - Every resolved value records *where it came from*.
3. **`oneadmin explain <model>[.<field>]`:** prints the resolved config and its origin, e.g. "read-only, from the convention at settings.py:12".
4. **`oneadmin schema --diff`:** shows how a code change alters the admin, so it can be reviewed in a pull request.
5. **Site-wide conventions:** rules over the description, e.g. `Conventions.readonly(r".*_at$")`, `Conventions.scope_by("tenant_id", ...)`, `Conventions.hide(r".*_secret$")`. You configure 200 models with a handful of rules.
6. **Type-safe options:**
   - `ModelAdmin[Post]`
   - `list_display = (Post.title, Post.author)`, with editor autocomplete and safe renames; strings still work
   - checked by mypy/pyright without a plugin
7. **Operation middleware:** `@admin.middleware async def m(op, call_next)` around read/create/update/delete/action. The core guarantees sit inside the chain. This becomes the home for webhooks, notifications, extra audit destinations and cache busting.
8. **ADR-0020 "Extensibility architecture".** It reopens the v1 non-goals on plugins, dashboards, uploads and i18n, and decides each explicitly.

**Exit**
- All existing tests pass unchanged.
- A new field type is one class plus, optionally, one widget.
- `explain` and `schema --diff` are covered by tests.
- The written design (`docs/design/extensibility.md`) is reviewed.

### Phase 2: The first five minutes, and 0.1 on PyPI (M, ~2–3 weeks) — **M8**
**Goal:** a stranger gets a working, impressive admin in five minutes.

**Tasks**
1. **`admin.register_all(Base)`:** every model, with good defaults (labels, list columns, search on text columns, filters on booleans/enums/dates).
2. **`oneadmin init`:** reads your models and writes an `admin.py` you can read, edit and commit, like React-Admin's "guessers" but as code.
3. **Dev mode:** works locally with no secret key and no HTTPS fuss. Loud warnings; it refuses to start in production.
4. **`oneadmin demo`:** a seeded 1M-row multi-tenant shop on SQLite or Docker PG, with the browser opened. The speed is felt, not claimed.
5. **Docs site** (MkDocs Material):
   - tutorial, how-to guides, reference generated from docstrings, concepts (scoping, keyset, audit)
   - screenshots and a 30-second GIF
6. **Public comparison page:** an honest feature matrix against sqladmin, Starlette-Admin, FastAdmin and Django admin, including where they win.
7. **Head-to-head benchmark harness** (`benchmarks/compare/`): the same models, data and hardware at 1M and 10M rows; p50/p95 per page depth; published with the scripts.
8. **"Coming from sqladmin" guide**, plus a small codemod that turns `ModelView` classes into `ModelAdmin` (`oneadmin convert sqladmin path/`).
9. **Release engineering:**
   - trusted publishing (OIDC), attestations
   - TestPyPI → PyPI **0.1.0**
   - CHANGELOG discipline
   - a SECURITY.md process with a private reporting channel

**Exit**
- Three people who have never seen the project reach a working admin on their own models in under 5 minutes (timed, notes recorded).
- 0.1.0 is installable from PyPI and works in a clean venv on Python 3.11–3.14.
- The benchmark results are published.

### Phase 3: Daily driver, at feature parity and beyond (L, ~5–6 weeks) — **M9**
**Goal:** nobody leaves because a basic feature is missing.

**Tasks**
1. **Layout as data, rendered by the server:**
   - `Page`, `Tabs`, `Tab`, `Row`, `Card`, `Aside`, `Fieldset`, `RelatedList`, `Inline`, `Stat`, `Timeline` in Python
   - permission-filtered per user, snapshot-tested
   - most of the features below become layout blocks rather than special cases
2. **Inline editing of related rows** (order lines inside an order): one transaction, per-row scoping and audit.
3. **Many-to-many editing; searchable foreign-key fields** with the target's scope (the existing relation picker, generalised).
4. **Export:** CSV/XLSX/JSON, streamed with server-side cursors, scoped and audited, size and time limits.
5. **Files and images:** a `Storage` protocol (local and S3-compatible ship), signed URLs, image previews, size/type limits.
6. **Editors:** JSON with schema validation; rich text and Markdown (lazy chunk); arrays.
7. **Editing in the list:** toggles and selects for fields marked `list_editable`, with versions.
8. **Computed columns:** `@display(sort=<SQL expr>)` methods; sortable when backed by an expression (keyset-safe through the compiler).
9. **Actions as small apps:** an input form from a Pydantic model; background execution with progress; results as a message, a file or a link.
10. **Command palette (Ctrl+K) and global search across models:** lazy chunk; keyboard navigation in lists (`j`/`k`, `e` to edit, `/` to search).

**Exit**
- A feature checklist against Django admin and sqladmin is ≥ 95% covered (the checklist is published).
- Initial JS is still ≤ 150 KB; each feature is a lazy chunk with its own budget.

### Phase 4: The standout features (L, ~4–5 weeks) — **M10**
**Goal:** features no other Python admin has, and the reasons people recommend it.

**Tasks**
1. **Undo anything.**
   - "Revert this change" and "Restore deleted row" from the history, built on the audit log, which already holds old values.
   - Reverts are new audited writes and respect scope and permissions.
   - Non-destructive actions show "Published 3 posts · Undo" instead of a confirmation dialog.
2. **Live collaboration:** presence ("Alice is editing this order") and lists that update when data changes. Server-Sent Events, pluggable broadcast (in-process; PostgreSQL `LISTEN/NOTIFY`).
3. **Activity and dashboards:**
   - a global audit feed with filters, and "what changed today"
   - `Stat`/`Chart`/`Table` blocks declared in Python and backed by scoped queries
4. **Performance made visible:**
   - a dev-mode panel on every page: queries, time, keyset/offset, the SQL
   - `oneadmin indexes --migration` writes an Alembic migration from the index advice
5. **Per-user preferences:**
   - saved views, column choice, density and pinned filters, stored in the database, never above what code allows
   - shareable view links
6. **Theming and branding:** `Theme(accent=..., radius=..., logo=..., font=...)` from Python as design tokens, with no rebuild; a light/dark toggle.
7. **Translations:** catalogs for UI strings; `verbose_name` through the app's gettext. English ships first, community languages follow.

**Exit**
- Undo works for update, delete and actions, with scope and permission tests.
- Presence works across two browsers in e2e.
- The performance panel is accurate (its query counts are checked by tests).

### Phase 5: Ecosystem (L, ~4–6 weeks) — **M11**
**Goal:** others extend it, so the maintainer isn't the bottleneck.

**Tasks**
1. **Resources protocol:** admin views over anything (an HTTP API, Stripe, Redis, a report) through `list/get/create/update/delete`. SQLAlchemy models are the built-in implementation (ADR-0017 pays off).
2. **Frontend plugin SDK (`@oneadmin/sdk`):**
   - a Vite template; `registerWidget`, `registerCell`, `registerPage`
   - React shared through an import map
   - same-origin serving (CSP intact), a versioned contract, contract tests
   - the escape hatch for the last 5%
3. **SQLModel and sync-engine support:** a second async engine documented, or a thread-pool adapter.
4. **Auth integrations:** OIDC/SSO backend (Google, Azure AD, Keycloak); tenant attributes for built-in users.
5. **Gallery:** example apps (SaaS multi-tenant, e-commerce, content), "recipes", and a plugin showcase.

**Exit:** at least two plugins written outside the core repo, built against the published SDK.

### Phase 6: 1.0 (M, ~2–3 weeks)
**Goal:** something people can bet a company on.

**Tasks**
- **API freeze:** every public name in `__all__` and every contract field reviewed; deprecations removed.
- **External audits:** a security review (OWASP ASVS L2 checklist; a paid review if funding allows) and a full WCAG 2.2 AA audit.
- **Upgrade guarantees:** a documented upgrade path from every 0.x release, and migration tests for OneAdmin's own tables.
- **Support policy:** 1.x supported for 12 months, Python/SQLAlchemy support windows written down.

**Exit:** 1.0.0 is released; the policies are published.

## 4. Running alongside every phase

| Track | Practice |
|---|---|
| **Performance** | Benchmarks in CI (1M rows): a list page regression > 20% fails the build. The query-count budget is enforced. |
| **Bundle** | Initial JS ≤ 150 KB gzip; every lazy chunk has its own budget; the size report goes in each PR. |
| **Accessibility** | axe on every e2e page; a keyboard-only journey test; manual screen-reader checks each phase. |
| **Security** | Threat model updated per phase; `pip-audit` + `pnpm audit`; a scoping test for every new endpoint. |
| **Docs** | No feature merges without docs and a changelog entry; every example in the docs is tested. |
| **Community** | CONTRIBUTING, issue templates, "good first issue" labels, GitHub Discussions, a public roadmap (this file). |
| **Dogfooding** | Every phase ends on `examples/shop` and on `backend/`, and later on adopters' apps. |

## 5. How we know it's working

All of these are public signals. There is no telemetry.

| Signal | Target by 1.0 |
|---|---|
| Time to first admin, for a newcomer | < 5 minutes (measured with real people each release) |
| List p95 at 10M rows, page 10,000 | < 20 ms (published benchmark) |
| Initial JS | ≤ 150 KB gzip |
| Feature parity checklist (Django admin + sqladmin) | ≥ 95% |
| Distinct outside issue reporters | 50+ |
| Plugins outside the core | 5+ |
| PyPI downloads / GitHub stars | trend only; never the goal itself |

## 6. Risks, and what we do about them

| Risk | Mitigation |
|---|---|
| **The public API grows faster than we can support it** | Extension points only via ADR; experimental APIs marked as such; a stable core plus plugins at the edges. |
| **Scope beyond one maintainer** | The order above front-loads what multiplies effort (Phase 1 core, Phase 5 ecosystem). Strict non-goals per phase. Community contributions from Phase 2 on. |
| **Server-driven UI feels limiting** | Layout blocks cover most needs; the plugin SDK covers the rest; per-field widget overrides from Phase 1. |
| **Bundle budget pressure** | Lazy chunks per feature; a budget per chunk; re-decide the 150 KB target only with measurements. |
| **Breaking early adopters** | API shape settled in Phase 1, *before* 0.1; deprecations with warnings for one minor version; codemods for renames. |
| **Competitors copy the headline features** | The guarantees (scoping, keyset, same-transaction audit) are architectural and hard to retrofit; keep executing. |

## 7. What we deliberately won't do

- Other ORMs as first-class backends. Resources (Phase 5) cover "admin over anything else" without lowest-common-denominator SQLAlchemy support.
- A hosted or SaaS version, or app-builder features (drag-and-drop screens, a query builder for end users).
- Telemetry of any kind.
- Server-rendered templates for end users.

## 8. Immediate next step

> **Update 2026-11-07:** the owner chose to build first and defer Phase 0 (CI, license, outside users). Phase 1 (M7) is done; Phase 2 (M8) is next.


**Phase 0:** your pilot pass, a GitHub remote with CI, and the license. Then Phase 1 starts with `docs/design/extensibility.md` and ADR-0020, written and reviewed before any code.
