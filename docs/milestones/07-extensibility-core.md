# M7: Extensibility core (ROADMAP Phase 1, ADR-0020)

## Steps (each lands green, with tests)
1. **`core/fields.py`:** the `FieldType` base, built-ins for every kind, `EmailField`/`URLField`/`MoneyField`.
   - `FieldMeta.type`.
   - `coerce`, `wire`, `filters`, `write_spec`, `cursor` and `contract` delegate to the type.
   - The schema gains `widget` + `widget_options`.
2. **Typed options:** attributes and `.desc()` accepted everywhere a name is; `ModelAdmin[M]`.
3. **Compiler with provenance:**
   - `ResolvedField`
   - conventions (`oneadmin.conventions`), `ignore_conventions`
   - `apply_scope` with `scope_by`
   - per-admin `field_types`
4. **CLI:** `oneadmin explain MODEL[.FIELD]`; `oneadmin schema [--diff FILE]`.
5. **Operation middleware** (`core/operations.py`), wired into the API router.
6. **Frontend:** cell/input registries keyed by `widget` (fallback `kind`); email, url and money widgets.
7. **Docs:** a "Customising OneAdmin" guide (layers 0–6), plus CHANGELOG and JOURNAL.

## Acceptance
- Every existing test passes unchanged in meaning (only test fixtures may need updating).
- A new field type is one Python class, plus optionally one widget.
- `explain` output and `schema --diff` are covered by tests; conventions and `scope_by` are tested on PG, including writes.
- The pilot `backend/` runs with conventions instead of repeated options.
