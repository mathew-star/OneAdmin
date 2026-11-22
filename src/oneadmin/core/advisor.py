"""Static index advice for ``oneadmin check``.

Keyset pagination is fast only when an index starts with the sort column (ADR-0003). This
module reads the SQLAlchemy ``Table`` metadata (no database connection) and reports sortable
and filterable columns that no index leads with.

It is advice, not an error. It can't see indexes created outside the model metadata (e.g.
only in migrations), and a tenant-scoped admin is best served by a composite index
``(tenant_id, sort_column, id)``, which the advisor accepts but can't demand.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Table, UniqueConstraint

from oneadmin.core.model_admin import ModelAdmin


@dataclass(frozen=True, slots=True)
class Advice:
    slug: str
    column: str
    reason: str

    def __str__(self) -> str:
        return f"{self.slug}.{self.column}: {self.reason}"


def _indexed_columns(table: Table) -> tuple[set[str], set[str]]:
    """(columns that lead some index, columns that appear anywhere in an index)."""
    leading: set[str] = set()
    anywhere: set[str] = set()
    groups: list[list[str]] = [[c.name for c in table.primary_key.columns]]
    groups += [[c.name for c in ix.columns] for ix in table.indexes]
    groups += [
        [c.name for c in con.columns]
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    ]
    for cols in groups:
        if cols:
            leading.add(cols[0])
            anywhere.update(cols)
    for column in table.columns:
        if column.index or column.unique:
            leading.add(column.name)
            anywhere.add(column.name)
    return leading, anywhere


def advise(admins: list[ModelAdmin]) -> list[Advice]:
    out: list[Advice] = []
    for admin in admins:
        c = admin.compiled
        table = c.meta.mapper.local_table
        if not isinstance(table, Table):
            continue
        leading, anywhere = _indexed_columns(table)
        for field in sorted(c.sort_allowed):
            column = c.meta.fields[field].column.name
            if column in leading:
                continue
            reason = (
                "sortable, but only a non-leading index column; deep pages may be slow"
                if column in anywhere
                else "sortable, but not indexed; deep pages will scan the table"
            )
            out.append(Advice(c.slug, field, reason))
        for field in c.filter_fields:
            column = c.meta.fields[field].column.name
            if column not in anywhere and c.meta.fields[field].kind not in ("boolean", "enum"):
                out.append(Advice(c.slug, field, "filterable, but not indexed"))
    return out
