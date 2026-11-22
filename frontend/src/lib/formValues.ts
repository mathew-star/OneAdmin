/**
 * Converting between wire values (what the API sends and accepts, ADR-0008/0018) and form
 * drafts (what inputs hold). Pure functions, so every rule is unit-tested.
 *
 * - Drafts are strings, except non-nullable booleans (a checkbox: `true`/`false`).
 * - Decimals and integers stay strings in the draft, and integers beyond 2^53 stay strings
 *   on the wire: nothing passes through a lossy float.
 * - Tz-aware datetimes are edited in the viewer's local time (`datetime-local`) and sent as
 *   UTC ISO strings; naive ones are edited and sent as stored.
 * - The server validates everything. Unparseable input is sent as typed, so the error
 *   message comes from the one validator that matters.
 */
import type { FieldSchema } from "@/api/types";

export type Draft = string | boolean;
export type Drafts = Record<string, Draft>;

/** The draft for a value read from the API. */
export function toDraft(field: FieldSchema, value: unknown): Draft {
  if (field.kind === "boolean" && !field.nullable) return value === true;
  if (value === null || value === undefined) return "";
  switch (field.kind) {
    case "boolean":
      return value ? "true" : "false";
    case "datetime":
      return typeof value === "string" ? datetimeDraft(value, field.tz_aware) : String(value);
    case "time":
      return typeof value === "string" ? value.slice(0, 8) : String(value);
    default:
      return String(value);
  }
}

export function initialDrafts(
  fields: readonly FieldSchema[],
  values: Record<string, unknown>,
): Drafts {
  return Object.fromEntries(fields.map((f) => [f.name, toDraft(f, values[f.name])]));
}

/** Empty drafts for a create form (unchecked booleans, blank inputs). */
export function blankDrafts(fields: readonly FieldSchema[]): Drafts {
  return Object.fromEntries(fields.map((f) => [f.name, toDraft(f, null)]));
}

const EMPTY = Symbol("empty");

/** The wire value for a draft, or `EMPTY` for a blank input. */
export function fromDraft(field: FieldSchema, draft: Draft): unknown {
  if (typeof draft === "boolean") return draft;
  const text = field.kind === "string" || field.kind === "text" ? draft : draft.trim();
  if (text === "") return EMPTY;
  switch (field.kind) {
    case "boolean":
      return text === "true";
    case "integer": {
      const n = Number(text);
      return /^[+-]?\d+$/.test(text) && Number.isSafeInteger(n) ? n : text;
    }
    case "float":
    case "interval": {
      const n = Number(text);
      return Number.isFinite(n) ? n : text;
    }
    case "datetime":
      if (!field.tz_aware) return text;
      return Number.isNaN(new Date(text).getTime()) ? text : new Date(text).toISOString();
    default:
      return text;
  }
}

/** Names of the fields whose draft differs from the initial one. */
export function changedFields(initial: Drafts, drafts: Drafts): string[] {
  return Object.keys(drafts).filter((name) => drafts[name] !== initial[name]);
}

/**
 * The request body.
 *
 * - **Create:** every non-blank writable field. Blank ones are omitted, so database
 *   defaults apply and the server reports missing required fields.
 * - **Update:** only the changed fields. A cleared input becomes `""` for text columns and
 *   `null` otherwise (rejected by the server for NOT NULL columns, with a clear message).
 */
export function buildPayload(
  mode: "create" | "update",
  fields: readonly FieldSchema[],
  initial: Drafts,
  drafts: Drafts,
): Record<string, unknown> {
  const changed = new Set(changedFields(initial, drafts));
  const body: Record<string, unknown> = {};
  for (const field of fields) {
    if (!field.writable) continue;
    const draft = drafts[field.name];
    if (draft === undefined || (mode === "update" && !changed.has(field.name))) continue;
    const value = fromDraft(field, draft);
    if (value !== EMPTY) body[field.name] = value;
    else if (mode === "update") body[field.name] = isText(field) && !field.nullable ? "" : null;
  }
  return body;
}

function isText(field: FieldSchema): boolean {
  return field.kind === "string" || field.kind === "text";
}

/** ISO datetime → `YYYY-MM-DDTHH:MM:SS` for a `datetime-local` input. */
function datetimeDraft(iso: string, tzAware: boolean): string {
  if (!tzAware) return iso.slice(0, 19);
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}
