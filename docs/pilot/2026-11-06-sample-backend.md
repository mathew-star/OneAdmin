# Pilot log: `backend/` sample blog (users, categories, posts)

The owner's sample app: FastAPI + SQLAlchemy 2 async + asyncpg + Alembic, PostgreSQL 16 on :5434.

## Integration steps (exactly what was done)
1. `cd backend && uv add --editable ..` installed `oneadmin` from the repo (resolved SQLAlchemy 2.1.8, FastAPI 0.162.0).
2. `src/app/admin.py`: an `AdminSite` using the app's own `async_session_maker`, plus three `ModelAdmin`s.
3. `src/app/config.py`: `ONEADMIN_SECRET_KEY` setting; a generated value goes in `.env` (git-ignored), with a placeholder in `.env.example`.
4. `src/app/main.py`: `admin.mount(app, path="/admin")`. That's two lines in the app.

## Verified (2026-11-06, `uvicorn app.main:app --port 8765`)
- `GET /admin/api/v1/schema`: 3 models. Label fields were inferred correctly (`username`, `name`, `title`). The `author`/`category` relations resolved to the registered admins.
- `GET /admin/api/v1/models/posts/rows`: FK labels arrive in the same query (`author.label = "bob_m"`). The nullable `category` FK works.
- Filters (`f.published=true`) plus search (`q=a`) give 5 rows with exact count 5.
- Cursor walk over posts with `limit=4`: all 8 posts, no duplicates. Every seeded `created_at` is identical, so ordering relied on the PK tiebreak.
- `sort=content` gives a 400 `invalid_sort`. A forwarded non-local client gets a 401.
- `/admin/` serves the fallback page (UI not built yet), with security headers.
- The app's own `/api/v1/posts/` still works. The app's test suite passes (2 tests).

## Findings
- **Seed IDs don't start at 1** (users are 8–10). That's harmless, and a reminder that the UI must never assume PK = 1.
- **Every seeded row has the same `created_at`.** A realistic case: the default `-created_at` sort works only because of the PK tiebreaker.
- **Temporary auth:** `LocalDevAuth` (development and loopback only). It is replaced by the built-in login in M3.

## Built-in login (M3), 2026-11-06
- Removed `LocalDevAuth`. Added `[tool.oneadmin] app = "app.admin:admin"` to `pyproject.toml` and `include_object` to `alembic/env.py`, in both the online and offline paths.
- `oneadmin check` before migrating exits 1 with "Run `oneadmin migrate`". `oneadmin migrate` goes none → 0001. `createsuperuser --password-stdin` works.
- **`alembic check` in the app reports "No new upgrade operations detected"**: its autogenerate leaves OneAdmin's tables alone.
- Over HTTP:
  - no cookie → 401
  - wrong password → 401 `invalid_credentials`
  - login → cookie `HttpOnly; Max-Age=43200; Path=/admin; SameSite=lax; Secure`
  - `Origin: https://evil.example` → 403
  - logout without CSRF → 403
  - authenticated posts list with author/category labels works
  - the DB holds a 64-char hash, not the token
- The index advisor flagged real gaps in the sample models: `posts.created_at` is the default sort but has no index; `users.created_at` likewise.

## Incident: sample data wiped by the app's own tests
`backend/tests/conftest.py` deletes every user, category and post in `DATABASE_URL`, which is the **dev database**, before and after each test. Running the app's tests (to check the mount didn't break them) emptied the seeded data. I reseeded with `python -m app.seed`; OneAdmin's admin user survived because it lives in its own table. Recommendation for the app: point the tests at a separate database.

## The UI (M4), 2026-11-06
- After `pnpm build:install`, a restart of `uvicorn app.main:app` serves the UI at `/admin/`. A restart is needed: `index.html` is read when the app starts.
- Walked through it in Chromium (light and dark):
  - deep link → login → back to the posts list
  - author/category labels linked to their rows
  - published as ✓/✗, tz-aware `created_at` in local time
  - filter popover, detail page
  - no console errors besides the expected 401 from the signed-out session probe
- **Found and fixed here:**
  - "Categorys" in the navigation (naive pluralisation)
  - the `author`/`category` columns appeared after `published`/`created_at`, because `/schema` reordered `list_display`
- Still true: `posts.created_at` (the default sort) has no index. Fine at 8 rows, not at 8 million.

## Writes, permissions, audit (M5), 2026-11-06
- `oneadmin migrate`: 0001 → 0002. `oneadmin check` now lists every model's permission codenames.
- `oneadmin createuser --email staff@example.com --password-stdin --grant posts.view` creates a staff user who sees only Posts.
- **Over HTTP**, with a script against the running app:
  - **Create:** creating a post → 201, with author/category labels in the response. Creating it again with the same slug → `409 integrity_error (ix_posts_slug)`.
  - **Mass assignment:** an unknown field → `400 validation_failed`.
  - **Concurrency:** update without `If-Match` → `428`; with the version → `200`; reusing the old version → `409 conflict`.
  - **Foreign keys:** `author_id` → a missing user gives `400 "no User with this key"`.
  - **History:** shows `update` (published false → true) and `create`, by admin@example.com.
  - **Staff user:** sees Posts only, with `view` only. Reading → 200; updating → 403; `delete_selected` → 403; Users → `404 unknown_model`.
  - **CSRF:** a write without `X-CSRF-Token` → `403 csrf_failed`.
  - **Delete:** with the version → 204, then reading it → 404.
- **Found and fixed here:**
  - `posts.updated_at` was writable, although the model sets it with `onupdate`, so any value typed would be overwritten.
  - Columns with `onupdate`/`server_onupdate` are now read-only by default.

## Editing UI (M6), 2026-11-06
- **Walked through in Chromium as admin@example.com:**
  - select two rows (the action bar appears)
  - Add post: the author is picked by searching users (scoped list)
  - create → edit → history (create + update with before/after) → delete with confirmation
  - no page errors
- **As staff@example.com (posts.view only):** no Edit link, no Delete button, no checkboxes.
- **Found here:**
  - **Clearing a post's title and saving succeeded:** the column is `NOT NULL`, but an empty string is a value. Required text fields now refuse blank values (`blank_fields` opts out). The empty-titled post (id 30) and a debugging post (id 31) were deleted through the admin API.
  - The bulk-action dropdown stretched across the bar (layout bug), fixed.
- My pilot script also left nothing behind: it deletes the post it creates.

## Customisation core (M7), 2026-11-07
- `backend/src/app/admin.py` was rewritten with typed options (`Post.title`, `Post.created_at.desc()`) and three conventions:
  - `created_at` is read-only everywhere (posts opt out with `ignore_conventions`)
  - `email` columns use `EmailField`
  - every boolean is filterable
- **`oneadmin explain` output, checked:**
  - `users.created_at`: not writable, "convention creation-time (src/app/admin.py:28)"
  - `users.is_active`: filterable by "convention boolean-filters"
  - `posts.created_at`: writable, labelled "Written" (`PostAdmin.labels`)
  - `users.email`: `EmailField()` by convention
- **Over HTTP:** `/schema` carries `widget: "email"` for `users.email`; posts' filters became `category_id, created_at, published`, with `published` added by the convention.
- No code in the app changed besides `admin.py`.

## Not yet tried here
- Real usage by the owner.
