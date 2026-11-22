"""Human- and machine-readable descriptions of compiled admins (ADR-0020).

- ``explain_model`` / ``explain_field``: what ``oneadmin explain`` prints. Every value is shown
  with the origin of the decision, e.g. "convention timestamps (app/admin.py:12)".
- ``describe_site``: a stable JSON-safe description of the whole configuration, for
  ``oneadmin schema``. Diffing two of them (``diff_descriptions``) shows exactly what a code
  change does to the admin, so configuration changes can be reviewed in a pull request.

Origins hold file:line locations, which churn with unrelated edits, so the JSON description
records only the *kind* of origin.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from oneadmin.core.conventions import DEFAULT, Origin

if TYPE_CHECKING:
    from oneadmin.core.compiler import CompiledAdmin
    from oneadmin.core.meta import FieldMeta
    from oneadmin.core.model_admin import ModelAdmin

_MODES = {"contains": "", "startswith": "^", "exact": "="}


# ---- explain ------------------------------------------------------------------------------
def explain_model(admin: ModelAdmin[Any]) -> list[str]:
    """The resolved configuration of one admin, with the origin of each setting."""
    c = admin.compiled
    p = c.provenance
    model = f"{c.model.__module__}.{c.model.__qualname__}"
    owner = f"{c.admin_class.__module__}.{c.admin_class.__qualname__}"
    rows: list[tuple[str, str, str]] = [
        ("list display", ", ".join(c.list_display), str(p.get("list_display", DEFAULT))),
        ("ordering", ", ".join(c.default_sort), str(p.get("ordering", DEFAULT))),
        (
            "search",
            ", ".join(_MODES[sf.mode] + sf.field.name for sf in c.search) or "-",
            str(p.get("search_fields", DEFAULT)) if c.search else "",
        ),
        ("label field", c.label.name, str(p.get("label_field", DEFAULT))),
        ("actions", ", ".join(c.actions) or "-", ""),
    ]
    for scope in c.scopes:
        rows.append(("scope", scope.field.name, str(p[f"scope.{scope.field.name}"])))
    lines = [f"{c.slug}: {owner} for {model}", ""]
    lines += _table(rows, indent=2)
    lines.append("")
    header = ("field", "type", "label", "shown", "writable", "filter", "sort")
    body = [_field_row(c, f) for f in c.meta.fields.values()]
    lines += _table([header, *body], indent=2)
    lines += ["", f"Run `oneadmin explain {c.slug}.<field>` to see why a field is configured so."]
    return lines


def explain_field(admin: ModelAdmin[Any], name: str) -> list[str]:
    """Every resolved setting of one field, each with its origin."""
    c = admin.compiled
    f = c.meta.field(name)  # raises ConfigurationError listing the valid names
    p = c.provenance
    shown = any(v.name == name for v in c.detail_fields)
    writable = name in c.write.fields
    column = f"{f.column.table.name}.{f.column.name} {f.column.type}" + (
        "" if f.nullable else " NOT NULL"
    )
    rows: list[tuple[str, str, str]] = [
        ("type", f.field_type.describe(), str(p[f"field.{name}.type"])),
        ("widget", f.field_type.widget_key, ""),
        ("shown", _yes(shown), str(p[f"field.{name}.visible"])),
    ]
    if shown:
        rows += [
            ("label", c.labels[name], str(p.get(f"field.{name}.label", DEFAULT))),
            ("writable", _yes(writable), _writable_origin(c, f)),
        ]
        if writable:
            spec = c.write.fields[name]
            rows.append(("required on create", _yes(spec.required), _required_reason(f)))
        filterable = name in c.filter_allowed
        rows.append(
            (
                "filterable",
                ", ".join(f.field_type.filter_ops) if filterable else "no",
                str(p[f"field.{name}.filterable"]) if filterable else "",
            )
        )
        rows.append(("sortable", _yes(name in c.sort_allowed), ""))
    return [f"{c.slug}.{name}  ({column})", "", *_table(rows, indent=2)]


def _field_row(c: CompiledAdmin, f: FieldMeta) -> tuple[str, ...]:
    shown = any(v.name == f.name for v in c.detail_fields)
    return (
        f.name,
        f.field_type.describe(),
        c.labels.get(f.name, "-"),
        _yes(shown),
        _yes(f.name in c.write.fields),
        _yes(f.name in c.filter_allowed),
        _yes(f.name in c.sort_allowed),
    )


def _writable_origin(c: CompiledAdmin, f: FieldMeta) -> str:
    origin = c.provenance.get(f"field.{f.name}.readonly", DEFAULT)
    if f.name in c.write.fields or origin != DEFAULT:
        return str(origin)
    return "default"


def _required_reason(f: FieldMeta) -> str:
    if f.nullable:
        return "nullable column"
    return "has a default" if f.has_default else "NOT NULL without a default"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _table(rows: Iterable[tuple[str, ...]], *, indent: int) -> list[str]:
    rows = list(rows)
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    pad = " " * indent
    return [
        pad + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in rows
    ]


# ---- schema description and diff -----------------------------------------------------------
def describe_site(admins: Iterable[ModelAdmin[Any]]) -> dict[str, Any]:
    """A stable description of every admin's configuration (sorted, JSON-safe)."""
    return {"models": {a.compiled.slug: _describe(a.compiled) for a in admins}}


def _describe(c: CompiledAdmin) -> dict[str, Any]:
    def origin(key: str) -> str:
        found: Origin | None = c.provenance.get(key)
        return found.kind if found is not None else "default"

    fields: dict[str, Any] = {}
    shown = {f.name for f in c.detail_fields}
    for f in c.meta.fields.values():
        entry: dict[str, Any] = {
            "type": f.field_type.describe(),
            "shown": f.name in shown,
            "type_from": origin(f"field.{f.name}.type"),
        }
        if f.name in shown:
            entry |= {
                "label": c.labels[f.name],
                "writable": f.name in c.write.fields,
                "required": f.name in c.write.fields and c.write.fields[f.name].required,
                "filter_ops": list(f.field_type.filter_ops) if f.name in c.filter_allowed else [],
                "sortable": f.name in c.sort_allowed,
            }
        fields[f.name] = entry
    return {
        "admin": f"{c.admin_class.__module__}.{c.admin_class.__qualname__}",
        "model": f"{c.model.__module__}.{c.model.__qualname__}",
        "list_display": list(c.list_display),
        "ordering": list(c.default_sort),
        "search": [_MODES[sf.mode] + sf.field.name for sf in c.search],
        "label_field": c.label.name,
        "actions": list(c.actions),
        "scopes": [s.field.name for s in c.scopes],
        "fields": fields,
    }


def dump(description: Mapping[str, Any]) -> str:
    return json.dumps(description, indent=2, sort_keys=True) + "\n"


def diff_descriptions(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Readable differences between two ``describe_site`` results (empty if identical)."""
    changes: list[str] = []
    _diff(old, new, "", changes)
    return changes


def _diff(old: Any, new: Any, path: str, out: list[str]) -> None:
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        for key in sorted(set(old) | set(new), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in old:
                out.append(f"+ {sub}: {_short(new[key])}")
            elif key not in new:
                out.append(f"- {sub}: {_short(old[key])}")
            else:
                _diff(old[key], new[key], sub, out)
    elif old != new:
        out.append(f"~ {path}: {_short(old)} -> {_short(new)}")


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 120 else text[:117] + "..."
