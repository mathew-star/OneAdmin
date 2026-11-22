import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type { FieldSchema, ModelSchema, RowOut } from "@/api/types";
import { cx, useApp } from "@/lib/app";
import type { Column } from "@/lib/columns";
import { isRelationValue } from "@/lib/format";
import { cycleSort, type ListSearch, parseSort } from "@/lib/listSearch";
import { RelationLink, Value } from "../Value";

interface DataTableProps {
  model: ModelSchema;
  columns: Column[];
  rows: RowOut[];
  search: ListSearch;
  /** True while the next page loads: the current rows stay visible, dimmed. */
  stale: boolean;
  /** Row selection for bulk actions; omitted when the user has no actions. */
  selection?: Selection | undefined;
}

export interface Selection {
  selected: ReadonlySet<string>;
  toggle: (pk: string) => void;
  /** Select every row on this page, or clear them all if they are all selected. */
  togglePage: () => void;
}

/**
 * The list table. Sorting, filtering and paging are server-side, so this is a plain semantic
 * `<table>` (ADR-0011): screen readers, Ctrl+F and copy/paste all work as expected.
 */
export function DataTable({ model, columns, rows, search, stale, selection }: DataTableProps) {
  const [primary] = parseSort(search.sort, model.default_sort);
  const allSelected =
    selection !== undefined && rows.length > 0 && rows.every((r) => selection.selected.has(r.pk));
  return (
    <div className="overflow-x-auto bg-surface">
      <table className={cx("w-full border-collapse text-left", stale && "opacity-60")}>
        <caption className="sr-only">{model.name_plural}</caption>
        <thead className="border-border border-b bg-surface-muted">
          <tr>
            {selection ? (
              <th scope="col" className="w-10 border-border border-r px-3 py-2">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={selection.togglePage}
                  aria-label="Select all rows on this page"
                  className="size-4 accent-[var(--oa-accent)]"
                />
              </th>
            ) : null}
            {columns.map((column) => {
              const sortable = column.type === "field" && column.field.sortable;
              const active = primary?.field === column.name ? primary : null;
              return (
                <th
                  key={column.name}
                  scope="col"
                  aria-sort={active ? (active.desc ? "descending" : "ascending") : undefined}
                  className={cx(
                    "whitespace-nowrap border-border/70 border-r px-4 py-2.5 text-left text-xs font-semibold text-muted last:border-r-0",
                    isNumeric(column) && "text-right",
                  )}
                >
                  {sortable ? (
                    <Link
                      to="/m/$slug"
                      params={{ slug: model.slug }}
                      search={cycleSort(search, column.name, model.default_sort)}
                      className={cx(
                        "inline-flex items-center gap-1.5 hover:text-fg",
                        active && "text-fg",
                      )}
                    >
                      {column.label}
                      <span
                        aria-hidden="true"
                        className="font-mono text-[10px] font-normal text-muted"
                      >
                        {fieldType(column.field.kind)}
                      </span>
                      <SortIcon state={active ? (active.desc ? "desc" : "asc") : null} />
                      <span className="sr-only">{sortHint(active)}</span>
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      {column.label}
                      <span
                        aria-hidden="true"
                        className="font-mono text-[10px] font-normal text-muted"
                      >
                        {column.type === "relation" ? "↗" : fieldType(column.field.kind)}
                      </span>
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr
              key={row.pk}
              aria-selected={selection ? selection.selected.has(row.pk) : undefined}
              className="transition-colors hover:bg-surface-muted aria-selected:bg-accent-soft"
            >
              {selection ? (
                <td className="w-10 border-border/70 border-r px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selection.selected.has(row.pk)}
                    onChange={() => selection.toggle(row.pk)}
                    aria-label={`Select row ${row.pk}`}
                    className="size-4 accent-[var(--oa-accent)]"
                  />
                </td>
              ) : null}
              {columns.map((column, index) => (
                <td
                  key={column.name}
                  className={cx(
                    "max-w-80 truncate border-border/70 border-r px-4 py-2.5 last:border-r-0",
                    isNumeric(column) && "text-right",
                    column.type === "field" &&
                      column.field.primary_key &&
                      "font-mono text-xs text-muted",
                  )}
                >
                  {index === 0 ? (
                    <Link
                      to="/m/$slug/r/$pk"
                      params={{ slug: model.slug, pk: row.pk }}
                      className="font-medium text-fg underline-offset-4 hover:text-accent hover:underline"
                    >
                      <Cell column={column} value={row.values[column.name]} />
                    </Link>
                  ) : (
                    <Cell column={column} value={row.values[column.name]} />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Cell({
  column,
  value,
  full = false,
}: {
  column: Column;
  value: unknown;
  full?: boolean;
}) {
  if (column.type === "relation") {
    return (
      <RelationLink
        relation={isRelationValue(value) ? value : null}
        target={column.relation.target}
      />
    );
  }
  return <FieldCell field={column.field} value={value} full={full} />;
}

/** A field's value: its widget's cell if one is registered, else the kind's rendering. */
function FieldCell({ field, value, full }: { field: FieldSchema; value: unknown; full: boolean }) {
  const { widgets } = useApp();
  const Custom = widgets.cell(field);
  if (Custom) return <Custom field={field} value={value} full={full} />;
  return <Value kind={field.kind} value={value} tzAware={field.tz_aware} full={full} />;
}

function isNumeric(column: Column): boolean {
  return (
    column.type === "field" &&
    ["integer", "decimal", "float"].includes(column.field.kind) &&
    !column.field.primary_key
  );
}

function SortIcon({ state }: { state: "asc" | "desc" | null }) {
  const Icon = state === "asc" ? ArrowUp : state === "desc" ? ArrowDown : ArrowUpDown;
  return <Icon className={cx("size-3.5", !state && "opacity-40")} aria-hidden="true" />;
}

function sortHint(active: { desc: boolean } | null): string {
  if (!active) return ", sort ascending";
  return active.desc ? ", reset to default order" : ", sort descending";
}

function fieldType(kind: string): string {
  const labels: Record<string, string> = {
    string: "str",
    text: "str",
    integer: "int",
    decimal: "dec",
    float: "num",
    boolean: "bool",
    datetime: "date",
    date: "date",
  };
  return labels[kind] ?? kind.slice(0, 4);
}
