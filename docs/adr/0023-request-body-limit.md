# ADR-0023: Enforce the write-body limit on bytes received

## Context

The write guard rejected a large `Content-Length`, but a client can omit or understate that header. The same limit did not apply to authentication writes. Admin requests use small JSON bodies; large uploads are outside this API's current contract.

## Options

- Rely on deployment server or proxy limits. These differ by deployment and are not a library guarantee.
- Count bytes while FastAPI reads the body. Route-specific dependencies run too late for some parsing paths.
- Buffer a bounded write body in ASGI middleware before dispatch. This gives auth and model routes one limit regardless of transfer encoding.

## Decision

`BodyLimitMiddleware` checks declared size and counts actual bytes for `POST`, `PUT`, `PATCH`, and `DELETE`. It rejects a request as soon as it exceeds 2 MiB and replays accepted bytes to the application. It sits inside the security-header middleware and outside route parsing. Read requests are not buffered.

## Consequences

Write requests use at most 2 MiB of body buffering per concurrent request. This is appropriate for the current JSON API; a future upload feature needs a separate streaming path and limit. Tests cover chunked requests without `Content-Length`, bodies exactly at the limit, and mounted auth routes.

## Revisit when

Revisit if the admin adds file uploads or another legitimate write format larger than 2 MiB.
