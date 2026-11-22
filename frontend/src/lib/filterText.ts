/** Human wording for filters: operator names and the text of an active filter's chip. */
import type { FieldSchema } from "@/api/types";
import type { ActiveFilter } from "./listSearch";

export const OP_LABELS: Record<string, string> = {
  eq: "is",
  ne: "is not",
  gt: "is after / greater than",
  gte: "is on or after / at least",
  lt: "is before / less than",
  lte: "is on or before / at most",
  in: "is one of",
  contains: "contains",
  icontains: "contains (any case)",
  startswith: "starts with",
  istartswith: "starts with (any case)",
  isnull: "is empty",
};

const ORDERED_WORDS: Record<string, { time: string; number: string }> = {
  gt: { time: "after", number: ">" },
  gte: { time: "on or after", number: "≥" },
  lt: { time: "before", number: "<" },
  lte: { time: "on or before", number: "≤" },
};

const TEMPORAL = new Set(["datetime", "date", "time"]);

/** The operator's wording for this field's kind ("after" for dates, "≥" for numbers). */
export function opLabel(op: string, field?: FieldSchema): string {
  const ordered = ORDERED_WORDS[op];
  if (ordered && field) return TEMPORAL.has(field.kind) ? ordered.time : ordered.number;
  return OP_LABELS[op] ?? op;
}

/** `Published is Yes`, `Total ≥ 10`, `Shipped at is empty`. */
export function describeFilter(
  filter: ActiveFilter,
  field: FieldSchema | undefined,
  locale?: string,
) {
  const label = field?.label ?? filter.field;
  if (filter.op === "isnull") {
    return `${label} ${filter.value === "true" ? "is empty" : "is not empty"}`;
  }
  return `${label} ${opLabel(filter.op, field)} ${valueText(filter, field, locale)}`;
}

function valueText(filter: ActiveFilter, field: FieldSchema | undefined, locale?: string): string {
  if (field?.kind === "boolean") return filter.value === "true" ? "Yes" : "No";
  if (filter.op === "in") return filter.value.split(",").join(", ");
  if (field?.kind === "datetime" && field.tz_aware) {
    const date = new Date(filter.value);
    if (!Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
        date,
      );
    }
  }
  return filter.value;
}

/**
 * Turn what a filter form's input holds into the wire value the server parses.
 * `datetime-local` inputs have no zone: for tz-aware columns they are read as the viewer's
 * local time and sent as UTC; naive columns get the value as typed.
 */
export function toWireValue(field: FieldSchema, op: string, input: string): string {
  const value = input.trim();
  if (op === "in") {
    return value
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)
      .join(",");
  }
  if (field.kind === "datetime" && op !== "isnull" && field.tz_aware) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toISOString();
  }
  return value;
}
