# Using the admin UI

Open the admin at the path you mounted it under, e.g. `http://localhost:8000/admin/`. The UI ships prebuilt inside the `oneadmin` wheel; nothing else needs installing.

## Signing in
- With the built-in authentication, sign in with an account created by `oneadmin createsuperuser`.
- After 5 failed attempts for one email (or 20 from one IP) within 15 minutes, sign-in is blocked for the rest of that window. The page says how long to wait.
- Sessions end after 2 hours without activity, or 12 hours after sign-in, whichever comes first. You then return to the login page, and afterwards to the page you were on.
- With a custom `auth_backend` (e.g. your app's SSO), there's no login page: the admin uses whatever your backend authenticates.

## Lists
Every list is a URL, so sorting, filters, search and the page are kept on reload, with the back button, and in shared links.

| You do | URL / API parameter |
|---|---|
| Click a column header: ascending → descending → default order | `sort=title`, `sort=-title` |
| Type in **Search** (applies after a short pause or Enter) | `q=...` |
| **Add filter** → field, condition, value | `f.<field>__<op>=value` |
| Remove a filter's chip (×) | |
| Page with first / previous / next / last | `cursor=...`, `last=1` |

Notes:
- **Only what the server allows is offered.**
  - Sortable columns come from `list_display` and `ordering` (or `sortable_fields`).
  - Filters come from `list_filter`.
  - The search box appears only with `search_fields`.
  - "Last page" appears only when the list uses keyset pagination.
- **There are no page numbers, by design.** Jumping to page N needs `OFFSET`, which gets slower the deeper it goes. Cursors cost the same on page 1 and page 10,000.
- **The table footer shows the visible range**, such as `Showing 1–50 of 1,000 rows`. The total is labelled as approximate or a lower bound when the server has not counted exactly. After a direct link to an older cursor without a known position, it shows the number of visible rows without guessing their absolute range.
- **Search** matches each word separately: `draft asyncpg` finds rows containing both words, in any searched field.
- **Counts:**

  | Shown | Means |
  |---|---|
  | `1,234 rows` | exact |
  | `10,000+ rows` | more than the cap; counting stops there |
  | `≈ 1.2M rows` | PostgreSQL's planner estimate, for large unfiltered tables |

  **Count exactly** asks for the precise number. On very large filtered tables this can take a few seconds, and it gives up after the server's timeout.
- **Datetimes:** columns with a time zone (`DateTime(timezone=True)`) are shown in your browser's time zone. Naive ones are shown as stored. Hover a value to see the raw ISO value.
- **Foreign keys** are shown by the related row's label, linked to it when that model is registered. A grey `#42` means the related row exists but is outside what you're allowed to see (`get_queryset` scoping).
- **Credential-like columns** (`password`, `token`, `secret`, ...) are never sent to the browser; see [`ModelAdmin`](model-admin.md).

## Detail
Click the first column of a row. Every visible field is listed, with foreign keys replaced by their related row. The breadcrumb returns to the list exactly as you left it.

The record view shows each field's label, underlying name and type. Editing keeps a link back to the record, and the save bar stays available when a long form scrolls.

**History** (on the detail page, under the fields) lists every change made through the admin: who, when, and each changed field's value before and after.

## Editing
What you see depends on your [permissions](editing-permissions-audit.md#permissions). A view-only user sees no Add, Edit or Delete buttons and no checkboxes.

- **Add** (top of a list) and **Edit** (on a row's page) open a form.
  - Required fields are marked `*`.
  - Fields you can't change are shown, not editable.
  - Related rows (an author, a category) are picked by searching their label. The choices come from what *you* can see.
  - Datetimes with a time zone are entered in your local time.
- **Saving an edit sends only the fields you changed.** If the server refuses something, each message appears under its field, with a summary at the top that links to them.
- **If someone else saved the same row while you were editing**, nothing is overwritten:
  1. The form shows which fields they changed.
  2. **Use the latest version, keep my changes** loads their version with your edits on top.
  3. Review the result and save again.
- **Delete** asks for confirmation first.
- **Bulk actions:**
  1. Tick rows (or the header box for the whole page).
  2. Pick an action in the bar that appears and press **Run**.
  3. Actions that change many rows or can't be undone ask first.

  An action applies to all selected rows or none: if any row is no longer allowed, nothing changes.
- **The selection belongs to the current view.** Changing page, sort or filters clears it.

## Accessibility
- Every control is reachable with the keyboard. "Skip to content" is the first Tab stop.
- Tables are real `<table>`s with sort state announced (`aria-sort`).
- Counts and loading are announced politely.
- Light and dark themes follow your operating system.
- The UI is checked with axe in the end-to-end tests.

## Security
- The page runs under a strict Content Security Policy (`script-src 'self'; style-src 'self'`): there is no inline code, and the server injects configuration as inert JSON.
- The session cookie is `HttpOnly`, so JavaScript never sees it.
- State-changing requests carry a CSRF token and must come from the same origin.
