# Contributing to OneAdmin

OneAdmin is pre-alpha. Please open an issue before adding a new public API or a large feature. Bug fixes, documentation corrections, and focused tests can go straight to a pull request.

## Set up

You need Python 3.11–3.14, [uv](https://docs.astral.sh/uv/), Node 24, pnpm 10, and Docker for PostgreSQL tests. The library's users do not need Node; contributors need it to build the bundled UI.

```bash
uv sync --all-extras --group docs
cd frontend && pnpm install --frozen-lockfile && cd ..
```

## Check a change

Run the checks relevant to your change before opening a pull request. CI runs the full matrix.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/unit
uv run pytest                  # requires Docker or ONEADMIN_TEST_PG_URL
uv run mkdocs build --strict
cd frontend && pnpm lint && pnpm check:api && pnpm test && pnpm build:install && cd ..
uv build
uv run python scripts/check_wheel.py dist/*.whl
```

The Playwright journey needs Chromium: from `frontend/`, run `pnpm exec playwright install chromium` and `pnpm test:e2e`. CI installs its system dependencies as well.

After changing API response models, run `uv run python scripts/export_openapi.py`, then `pnpm gen:api` in `frontend/`, and commit both generated files. CI rejects stale generated types.

## Design and review rules

- Read the [architecture](docs/architecture.md) and the invariants in [CLAUDE.md](CLAUDE.md) before changing core, auth, or write paths.
- Keep `core/` and `auth/` independent of HTTP and UI packages. Keep per-site state on `AdminSite`.
- Every read and write must preserve tenant scope, authorization, and the documented audit behavior. Add an integration or security test when changing these paths.
- Treat a name in `oneadmin.__all__`, a documented import, a CLI command, an extension hook, or a wire contract as a compatibility promise. Explain changes to these in the pull request and update docs and `CHANGELOG.md`.
- Add useful docstrings to public types and functions: purpose, parameters, return value, exceptions, and any security or transaction behavior callers need to know. Avoid repeating type annotations in prose.
- Use the existing ADR template in `docs/adr/` for a non-trivial architectural decision. Keep commits focused and use conventional commit messages.
- Do not weaken a test or lint rule merely to make a change pass. State a deliberate exception beside the code.

The [release process](docs/release-process.md) explains the extra checks required before publishing a version. Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.
