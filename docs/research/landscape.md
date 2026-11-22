# Landscape: Python admin panels and generic CRUD UIs

Researched 2026-11-06. Repo stats come from the GitHub REST API, and versions and dependencies from PyPI JSON, both fetched the same day. "Source-verified" means I downloaded and read the wheel from PyPI. Anything I didn't verify that way is labeled.

## Summary table

| Project | Latest | Stars | Open issues | Last push | License | Rendering | ORM | Async |
|---|---|---|---|---|---|---|---|---|
| sqladmin (smithyhq, formerly aminalaee) | 0.32.0 (2026-09-20) | 2,852 | n/a | 2026-10-01 | BSD-3 | Jinja2 + WTForms SSR (Tabler) | SQLAlchemy only (sync and async) | partial |
| Starlette-Admin | 1.0.3 (2026-10-24) | 1,071 | 19 | 2026-11-02 | MIT | Jinja2 SSR + jQuery/DataTables | SQLAlchemy, MongoEngine, Beanie, ODMantic | partial |
| FastAdmin | 0.10.0 (2026-07-16) | 343 | 1 | 2026-11-03 | MIT | React SPA (prebuilt, shipped in wheel) | SQLAlchemy, Tortoise, Django, Pony | yes |
| fastapi-admin | 1.0.4 (**2022-06-08**) | 3,828 | 78 | 2025-04-05 | Apache-2.0 | Jinja2 SSR (Tabler) | Tortoise only | yes |
| Piccolo Admin | 1.14.0 (2026-06-19) | 466 | 39 | 2026-06-19 | MIT | Vue SPA (prebuilt, shipped in wheel) | Piccolo only | yes |
| Flask-Admin | 2.2.1 (2026-09-21) | 6,073 | 131 | 2026-11-03 | BSD-3 | Jinja2 + WTForms SSR | SQLAlchemy, Peewee, Mongo… | no (WSGI) |
| Django admin | (Django) | 91.5k | n/a | active | BSD-3 | Django templates SSR | Django ORM | mostly sync |
| React-Admin | (npm) | 27.0k | 58 | 2026-11-05 | MIT (EE paid) | React SPA framework | any (data providers) | n/a |
| Refine | (npm) | 36.0k | 59 | 2026-09-10 | MIT | React meta-framework | any | n/a |
| Retool / Appsmith / Budibase-style | SaaS/OSS | n/a | n/a | n/a | mixed | hosted builders | DB connectors | n/a |

## Per-project notes

### sqladmin (source-verified, `sqladmin/models.py` in 0.32.0)
- **Architecture:** a Starlette sub-app. `ModelView` classes have class attributes much like Django's (`column_list`, `column_searchable_list`, `form_columns`…). WTForms builds the forms and Jinja2 renders them server-side.
- **Extension model:** subclass `ModelView` and override `list_query`, `count_query`, `search_query` and `sort_query`. You can also add custom `BaseView`s with `@expose`, or override templates.
- **Pagination and counting (verified):** every list request runs `select(func.count()).select_from(stmt.subquery())` and then `.limit().offset()`. The count is exact and the pagination is OFFSET-based. Deep pages and large tables both pay O(N).
- **Relationship loading:** list pages `selectinload` the relationships named in `column_list`. Detail pages used to `joinedload` every relationship, and issue #704 reports that this produced a cartesian explosion (10×15×37 = 5,550 rows where 63 were needed).
- **Auth:** you implement an `AuthenticationBackend` subclass yourself, on Starlette's signed-cookie `SessionMiddleware`. There are no users, roles or audit log, and I found no CSRF module in the package (grep for `csrf` in 0.32.0 returns nothing).
- **Strengths:** small, readable code, good SQLAlchemy coverage, the most popular choice for FastAPI.
- **Recurring complaints** (GitHub search, sorted by reactions):
  - per-column filtering (#498, 35 reactions, added later)
  - **inline models are still missing** (#394, open since 2022, 26 reactions)
  - multiple views per model break URLs (#681, open)
  - **hooks don't receive the DB session, so audit writes can't be atomic** (#925, open)
  - composite PKs (#63)
  - timezone-aware datetimes edited incorrectly (#796)
  - details page slow with many relations (#704)

### Starlette-Admin (source-verified, `contrib/sqla/view.py` in 1.0.3)
- **Architecture:** Jinja2 templates, with list views loading JSON over AJAX into DataTables. The field system is declarative (`StringField`, `HasOne`…) and works across several ORMs.
- **Pagination:** `.offset(skip).limit(limit)` plus `select(func.count()).select_from(model)`, again exact count and OFFSET.
- **Performance complaint:** #686 reports that the first list page of a 2M-row table took **14 s** (about 2 s at under 1M rows). The user asks how to cap pagination. Cause: exact count plus OFFSET.
- **Security:** it has a `security/csrf.py` (CSRF tokens in forms). Auth is a pluggable `AuthProvider`. #873 reports `authenticate()` being called on every static-file request.
- **Strengths:** multi-ORM, good docs, i18n, export (CSV/Excel/PDF through DataTables), row actions.
- **Weaknesses:**
  - the frontend is a jQuery/DataTables stack (#806 asked to stop loading the Inter CSS from a CDN)
  - enum filters didn't constrain values (#515)
  - requested features: FK filters (#717, #745) and default filters (#601)

### FastAdmin (source-verified)
- **Architecture:** a prebuilt React SPA in the wheel plus a JSON API. It is framework-agnostic (FastAPI, Flask, Django) and ORM-agnostic. This is the closest architectural analogue to our plan.
- **Bundle (measured from the wheel):** `index.min.js` is 3.47 MB raw and **1.04 MB gzipped**, as a single chunk, plus seven roughly 98 KB-gzip "worker" chunks. That gives a concrete bar to beat.
- **Auth:** a JWT (`pyjwt`) in a cookie, with a configurable SameSite setting. The Django adapter decorates its endpoints with `@csrf_exempt`.
- **Weaknesses:** requires Python ≥3.12; one maintainer; supporting many ORMs and frameworks means a lowest-common-denominator SQLAlchemy feature set.

### fastapi-admin
- Tortoise-only, and the last release was in 2022. The project is effectively unmaintained. Its high star count is a sign of demand, not of quality.

### Piccolo Admin (source-verified)
- A Vue SPA prebuilt into the wheel (`dist/`). The main JS chunk is **1.63 MB raw / 323 KB gzip**. It only works with Piccolo, has polished UX, and its sessions and auth come from `piccolo_api`.
- Takeaway: it shows that "SPA in a wheel" works and that users like it, but it is tied to one ORM.

### Flask-Admin / Django admin (design inspiration only)
- **Django admin** is the reference for what a good declarative API looks like:
  - `list_display`, `list_filter`, `search_fields` (`^`, `=`, `@` prefixes), `readonly_fields`, `fieldsets`
  - `inlines`, `actions`, `autocomplete_fields`, `list_select_related`, `show_full_result_count`
  - `get_queryset`, `has_*_permission`, `ModelAdmin.save_model`, `LogEntry`

  Its known weaknesses are the old-fashioned UI, OFFSET pagination with exact counts (hence `show_full_result_count`), and the N+1 queries you get from `__str__` in lists.
- **Flask-Admin** has inline models and a rich filter set, but it is WSGI-only and its UI is dated.

### React-Admin / Refine (frontend inspiration)
- Both are mature SPA frameworks built on "data provider" abstractions. Both assume **you write per-resource frontend code**, which our users don't want.
- Ideas worth borrowing:
  - optimistic updates and undo
  - URL-as-state for list views
  - saved filters
  - React-Admin's "guessers": schema-driven defaults that print code you can customise
- React-Admin's enterprise features (audit log, RBAC, realtime) are paid. That suggests an audit log and RBAC are features people will pay for, which makes them good differentiators to ship for free.

### Retool / Appsmith-style builders
- These are hosted or self-hosted app builders, not libraries. Their strengths are ad-hoc queries and dashboards; their weaknesses are a separate deployment, a separate auth system, and drift from the app's domain logic. We are not competing with them. The gap we fill is **admin that lives in your codebase and reuses your models, sessions and auth**.

## Gaps: what would make someone switch?

These are grounded in the issues cited above.

1. **Large-table performance.** sqladmin and Starlette-Admin both run exact `count(*)` plus OFFSET on every list request (verified in source). #686 (14 s on 2M rows) is the canonical complaint. Our experiment (technical-findings §2) confirms that on 1M rows OFFSET at the midpoint costs about 86 ms and reads about 502k buffers, while keyset costs 0.6 ms and reads 53 buffers.
2. **Atomic hooks and audit.** sqladmin #925 asks for the session in hooks so audit writes can be transactional. We ship an audit log written in the same transaction.
3. **Inline/related editing.** sqladmin #394 has been open for four years.
4. **Real auth out of the box.** Users, superuser creation, CSRF, rate limiting, roles. sqladmin leaves all of this to the user.
5. **Multi-tenancy as a first-class safety property.** None of the competitors does this; each leaves it to a `list_query` override that is easy to forget on detail, update, delete, action and export paths. That is an IDOR footgun.
6. **Modern, fast UI without Node for users.** FastAdmin and Piccolo prove the delivery model works, but their bundles are 1.04 MB and 323 KB gzip respectively. A lean bundle that starts fast is a measurable win.
7. **Typed, correct edge cases:** composite PKs, timezone datetimes, enums, and multiple admins on one model.

## Positioning conclusion

"SQLAlchemy-only, async-only, schema-driven SPA, with auth, audit and tenancy built in, and correct on 1M+ rows." Supporting several ORMs is explicitly a non-goal: being SQLAlchemy-only is what lets us use SQLAlchemy's introspection and loader strategies properly, and it is the trade-off FastAdmin got wrong.
