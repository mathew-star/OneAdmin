# 0014: Project name — `oneadmin`

- Status: accepted (owner delegated the choice, 2026-11-06)
- Date: 2026-11-06

## Context
The draft said "NexusAdmin", the old CLAUDE.md said "youradmin", the repo is "OneAdmin". A rename after a public release breaks imports, PyPI links and docs.

## Options considered
- `nexus-admin`: "Nexus" is heavily used (Sonatype Nexus, many products); poor searchability.
- `oneadmin` / import `oneadmin`: matches the repo, short, one word, same distribution and import name (no `pip install x` / `import y` confusion). Unclaimed on PyPI (re-checked 2026-11-06, HTTP 404 for `oneadmin` and `one-admin`).

## Decision
Distribution `oneadmin`, import `oneadmin`, CLI `oneadmin`, display name "OneAdmin". Tagline: "one admin for your FastAPI + SQLAlchemy app".

## Consequences
- Reserve the name on PyPI with the first TestPyPI/PyPI upload (M-release). Until then someone else could claim it; acceptable risk, low likelihood.
- A trademark search was not done; revisit if a conflict surfaces.
