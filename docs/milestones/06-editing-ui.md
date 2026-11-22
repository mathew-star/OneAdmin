# M6: Editing UI

Builds the UI for M5's write API (ADR-0018/0019). The design rules of M4 still apply: the URL is the state, the server is the source of truth, strict CSP, axe-clean, initial JS ≤150 KB gzip.

## Design
- **The server decides what is editable.**
  - Forms are generated from `/schema`: `writable` fields become inputs, everything else is shown read-only, and `required` marks fields needed on create.
  - Buttons (Add, Edit, Delete, actions) appear only when `permissions`/`actions` allow them. The server checks again anyway.
- **Edits send only the fields that changed**, with `If-Match: <version>`, so a concurrent change to another field is never overwritten.
- **Validation errors:** `400 validation_failed` puts each message under its field (`aria-invalid` + `aria-describedby`), plus a summary at the top that receives focus. Form-level errors (`""`, `out_of_scope`, `forbidden`, `integrity_error` without a field) appear in the summary.
- **Conflicts (`409 conflict`):**
  - The form shows which fields someone else changed, using `error.current`.
  - "Use the latest version" rebases: the new base is the current row, the user's own edits are kept on top, and the version is updated. The user reviews and saves again. Nothing is lost silently.
- **Values:** one pure module (`lib/formValues.ts`, unit-tested) converts wire values ⇄ input drafts per kind.
  - Decimals and big integers stay strings.
  - Tz-aware datetimes are edited in local time and sent as UTC; naive ones are edited as stored.
  - An empty input on a nullable field means `null`. On create, an empty optional field is omitted, so the database default applies.
- **Foreign keys:** a combobox (`RelationPicker`) that searches the *target* model's list endpoint, so results are scoped exactly like everything else. It shows labels and sends the key. An unregistered target falls back to a plain key input.
- **Deletes and actions** go through a confirmation dialog (Radix AlertDialog) when they are destructive or declare `confirm`. Outcomes are announced in a live-region toast.
- **Selection:** a checkbox column plus "select page", cleared when the view changes. The action bar appears when rows are selected.
- **History:** a section on the detail page lists the audit entries (who, when, what changed: old → new).
- **Bundle:** create/edit pages, the form, the picker and history are lazily loaded route chunks. The initial JS budget is unchanged.

## Tasks
1. `ApiClient`: `patch`/`delete` with extra headers; `ApiError.fields` / `.current`.
2. `lib/formValues.ts` + tests; `api/mutations.ts` (create/update/delete/action + cache invalidation).
3. `RecordForm`, `FieldInput`, `RelationPicker`; `CreatePage` (`/m/$slug/new`) and `EditPage` (`/m/$slug/r/$pk/edit`), both lazy.
4. Detail page: Edit/Delete buttons, history section. List page: Add button, selection, action bar, confirm dialog, toasts.
5. Tests:
   - **Vitest:** formValues; form flows on the fake API (create, field errors, conflict rebase, changed-fields-only PATCH); actions with confirm; delete.
   - **Playwright + axe:** the e2e journey adds create → edit → conflict → action → delete → history.
6. Docs: update the UI guide; CHANGELOG, JOURNAL, pilot log.

## Acceptance
- All suites green; initial JS ≤150 KB gzip; no CSP violations.
- In `backend/`, in a real browser: create, edit and delete a post, run a bulk action, and see the history. A view-only staff user sees no edit controls.
