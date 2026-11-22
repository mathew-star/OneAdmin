# The HTTP API (`/admin/api/v1`)

- The UI uses this API, and your scripts can too.
- Responses are JSON.
- Errors always look like `{"error": {"code": "...", "message": "...", "param": "..."}}`.

## Auth (built-in backend)
| Method & path | Body | Result |
|---|---|---|
| `POST /auth/login` | `{"email", "password"}` | `{"user", "csrf_token"}` and the session cookie. `401 invalid_credentials`, `429 rate_limited` |
| `GET /auth/session` | | `{"user", "csrf_token"}` or `401` |
| `POST /auth/logout` | `{}` + `X-CSRF-Token` | `204` |

## Models
| Method & path | Result |
|---|---|
| `GET /schema` | The models *you* can view: fields (with `writable`/`required`), filters, relations, your `permissions` and the `actions` you may run (`contract_version: 1`). Supports `ETag` / `If-None-Match`. |
| `GET /models/{slug}/rows` | A page: `{"rows": [{"pk", "values"}], "next_cursor", "prev_cursor", "pagination", "count"}` |
| `GET /models/{slug}/rows/{pk}` | One row with its `version` (also the `ETag`), or `404` |
| `GET /models/{slug}/count` | Exact count of the filtered list |
| `GET /models/{slug}/rows/{pk}/history?limit=50` | Audit entries of the row, newest first |

## Writes
Every write needs `Content-Type: application/json` (except `DELETE`) and a same-origin `Origin`. With the built-in login it also needs `X-CSRF-Token`.

| Method & path | Body | Result |
|---|---|---|
| `POST /models/{slug}/rows` | `{"field": value, ...}` | `201` + the row |
| `PATCH /models/{slug}/rows/{pk}` | the fields to change + `If-Match: <version>` | `200` + the row |
| `DELETE /models/{slug}/rows/{pk}` | `If-Match: <version>` | `204` |
| `POST /models/{slug}/actions/{name}` | `{"pks": ["1", "2"]}` | `{"count", "message"}` |

Rules and error codes: [Editing, permissions & audit](editing-permissions-audit.md).

### List parameters
- `sort=-created_at,title`
- `q=search words`
- `limit=1..500`
- `cursor=<next_cursor or prev_cursor>`
- `last=true` (final page)
- `count=false` (skip the count)

### Filters
`f.<field>=value` or `f.<field>__<op>=value`:

| Type | Operators |
|---|---|
| text | `eq` `ne` `in` `contains` `icontains` `startswith` `istartswith` |
| numbers, dates | `eq` `ne` `gt` `gte` `lt` `lte` `in` |
| datetimes, floats | `gt` `gte` `lt` `lte` |
| booleans | `eq` |
| enums, UUIDs | `eq` `ne` `in` |
| any nullable | `isnull=true\|false` |

`in` takes comma-separated values (at most 100).

### Value encoding
- Decimals are sent as strings.
- Integers beyond ±2^53 are sent as strings, because JavaScript loses precision.
- Datetimes use ISO 8601.
- A relation is sent as `{"pk": "...", "label": "..."}`.
- Composite primary keys are encoded as base64url JSON in `pk`.
