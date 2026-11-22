/**
 * Turning wire values into display text. Pure functions, so every rule is unit-tested.
 *
 * The wire format (ADR-0008) keeps precision-sensitive values as strings: decimals, and
 * integers beyond ±2^53. They are shown exactly as received and never parsed into numbers.
 */
import type { CountOut, FieldKind, RelationValue } from "@/api/types";

export type Display =
  | { type: "empty" }
  | { type: "boolean"; value: boolean }
  | { type: "text"; text: string; title?: string; mono?: boolean; numeric?: boolean }
  | { type: "badge"; text: string };

export interface FormatOptions {
  tzAware?: boolean;
  /** Detail views show long values in full; lists truncate them. */
  full?: boolean;
  locale?: string | undefined;
}

const LIST_JSON_LIMIT = 80;

export function display(kind: FieldKind, value: unknown, options: FormatOptions = {}): Display {
  if (value === null || value === undefined) return { type: "empty" };
  switch (kind) {
    case "boolean":
      return typeof value === "boolean" ? { type: "boolean", value } : text(String(value));
    case "integer":
    case "decimal":
    case "float":
      return { type: "text", text: String(value), numeric: true };
    case "datetime":
      return typeof value === "string" ? formatDateTime(value, options) : text(String(value));
    case "date":
      return typeof value === "string" ? formatDate(value, options.locale) : text(String(value));
    case "interval":
      return typeof value === "number" ? text(formatSeconds(value)) : text(String(value));
    case "enum":
      return { type: "badge", text: String(value) };
    case "uuid":
      return { type: "text", text: String(value), mono: true };
    case "json":
    case "array":
      return formatJson(value, options.full ?? false);
    case "binary":
      return { type: "text", text: "(binary)", title: "Binary data isn't shown" };
    default:
      return text(String(value));
  }
}

export function isRelationValue(value: unknown): value is RelationValue {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as RelationValue).pk === "string" &&
    "label" in value
  );
}

/**
 * tz-aware timestamps are shown in the viewer's time zone (the ISO value is kept as the
 * tooltip). Naive ones are shown as stored: there's no zone to convert from.
 */
export function formatDateTime(iso: string, options: FormatOptions = {}): Display {
  if (!options.tzAware) return { type: "text", text: naive(iso), title: iso, numeric: true };
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return text(iso);
  const formatted = new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
  return { type: "text", text: formatted, title: iso };
}

/** Dates have no time zone: format them in UTC so the calendar day never shifts. */
export function formatDate(iso: string, locale?: string): Display {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return text(iso);
  const [, y, m, d] = match;
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  const formatted = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" });
  return { type: "text", text: formatted.format(date), title: iso };
}

/** `2026-11-06T09:30:00.123456` → `2026-11-06 09:30:00` (fractional seconds hidden). */
function naive(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+$/, "");
}

export function formatSeconds(total: number): string {
  const sign = total < 0 ? "-" : "";
  let rest = Math.abs(total);
  const days = Math.floor(rest / 86_400);
  rest -= days * 86_400;
  const h = Math.floor(rest / 3600);
  const m = Math.floor((rest % 3600) / 60);
  const s = rest % 60;
  const clock = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${pad(s)}`;
  return `${sign}${days ? `${days}d ` : ""}${clock}`;
}

/** Two-digit seconds, keeping milliseconds when present: `5` → `05`, `1.5` → `01.500`. */
function pad(seconds: number): string {
  const text = Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(3);
  const wholeDigits = text.indexOf(".") < 0 ? text.length : text.indexOf(".");
  return "0".repeat(Math.max(0, 2 - wholeDigits)) + text;
}

function formatJson(value: unknown, full: boolean): Display {
  const json = JSON.stringify(value, null, full ? 2 : undefined) ?? String(value);
  if (full || json.length <= LIST_JSON_LIMIT) return { type: "text", text: json, mono: true };
  return { type: "text", text: `${json.slice(0, LIST_JSON_LIMIT - 1)}…`, title: json, mono: true };
}

function text(value: string): Display {
  return { type: "text", text: value };
}

// ---- counts ----------------------------------------------------------------------------

export interface CountText {
  /** Short form for the toolbar, e.g. "≈ 1.2M rows", "10,000+ rows", "1,234 rows". */
  short: string;
  /** Full sentence for screen readers and tooltips. */
  long: string;
}

export function formatCount(count: CountOut, locale?: string): CountText | null {
  if (count.value === null) {
    return count.method === "timeout"
      ? { short: "Many rows", long: "Counting took too long; the total is unknown." }
      : null;
  }
  const exact = new Intl.NumberFormat(locale).format(count.value);
  if (count.exact) {
    const text = `${exact} ${count.value === 1 ? "row" : "rows"}`;
    return { short: text, long: text };
  }
  if (count.method === "estimate") {
    const compact = new Intl.NumberFormat(locale, {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(count.value);
    return { short: `≈ ${compact} rows`, long: `About ${exact} rows (estimated)` };
  }
  return { short: `${exact}+ rows`, long: `More than ${exact} rows` };
}
