/**
 * List state lives in the URL. These helpers translate between the router's search object
 * and the API's query parameters, which have the same names on purpose:
 *
 * | URL / API          | Meaning                                              |
 * |--------------------|------------------------------------------------------|
 * | `sort`             | `-created_at,id` (comma separated, `-` = descending) |
 * | `q`                | search text                                          |
 * | `f.<field>__<op>`  | one filter, e.g. `f.total__gte=10`                    |
 * | `cursor`           | opaque, signed page cursor from the server           |
 * | `last`             | `1` = jump to the final page (keyset mode only)      |
 * | `start`            | first visible row number (UI only; never sent to API) |
 *
 * Every value stays a string: the server parses and validates them per column type, so the
 * client never guesses (no `"1e3"` silently becoming `1000`).
 */
import type { QueryParams } from "@/api/client";

export const FILTER_PREFIX = "f.";

export type FilterKey = `f.${string}`;

export type ListSearch = {
  sort?: string;
  q?: string;
  cursor?: string;
  last?: "1";
  start?: string;
} & { [key: FilterKey]: string };

export interface ActiveFilter {
  key: FilterKey;
  field: string;
  op: string;
  value: string;
}

export interface SortKey {
  field: string;
  desc: boolean;
}

/** Sanitise a raw search object from the router: unknown keys and non-strings are dropped. */
export function parseListSearch(raw: Record<string, unknown>): ListSearch {
  const out: ListSearch = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== "string" || value === "") continue;
    if (key === "sort" || key === "cursor") out[key] = value;
    else if (key === "q") {
      const q = value.trim();
      if (q) out.q = q;
    } else if (key === "last") {
      if (value === "1") out.last = "1";
    } else if (key === "start") {
      if (/^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))) out.start = value;
    } else if (isFilterKey(key)) out[key] = value;
  }
  return out;
}

/** The `/models/{slug}/rows` query for this view. */
export function toApiQuery(search: ListSearch, extra: QueryParams = {}): QueryParams {
  const query: QueryParams = { sort: search.sort, q: search.q, cursor: search.cursor };
  if (search.last) query.last = "true";
  for (const filter of activeFilters(search)) query[filter.key] = filter.value;
  return { ...query, ...extra };
}

/** Only what decides *which* rows match (not their order or page): the count's cache key. */
export function matchSignature(search: ListSearch): string {
  const parts = activeFilters(search).map((f) => `${f.key}=${f.value}`);
  parts.sort();
  if (search.q) parts.push(`q=${search.q}`);
  return parts.join("&");
}

export function activeFilters(search: ListSearch): ActiveFilter[] {
  const filters: ActiveFilter[] = [];
  for (const [key, value] of Object.entries(search)) {
    if (!isFilterKey(key) || typeof value !== "string") continue;
    filters.push({ key, value, ...splitFilterKey(key) });
  }
  return filters;
}

/**
 * The filter key for `field` and `op`. The operator is always explicit: the server splits on
 * the *last* `__`, so a field whose own name contains `__` stays unambiguous.
 */
export function filterKey(field: string, op: string): FilterKey {
  return `${FILTER_PREFIX}${field}__${op}`;
}

export function splitFilterKey(key: FilterKey): { field: string; op: string } {
  const body = key.slice(FILTER_PREFIX.length);
  const at = body.lastIndexOf("__");
  return at < 0 ? { field: body, op: "eq" } : { field: body.slice(0, at), op: body.slice(at + 2) };
}

/** A view of the same rows from the first page: changing what matches invalidates cursors. */
export function firstPage(search: ListSearch): ListSearch {
  const { cursor: _cursor, last: _last, start: _start, ...rest } = search;
  return rest;
}

export function withFilter(search: ListSearch, field: string, op: string, value: string) {
  const next: ListSearch = firstPage(search);
  // One condition per field and operator: replace an existing one rather than stacking.
  next[filterKey(field, op)] = value;
  return next;
}

export function withoutFilter(search: ListSearch, key: FilterKey): ListSearch {
  const { [key]: _removed, ...rest } = firstPage(search);
  return rest;
}

export function withSearch(search: ListSearch, q: string): ListSearch {
  const { q: _q, ...rest } = firstPage(search);
  const trimmed = q.trim();
  return trimmed ? { ...rest, q: trimmed } : rest;
}

export function parseSort(sort: string | undefined, fallback: readonly string[]): SortKey[] {
  const parts = sort ? sort.split(",") : [...fallback];
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) =>
      part.startsWith("-") ? { field: part.slice(1), desc: true } : { field: part, desc: false },
    );
}

/**
 * Clicking a column header cycles: ascending → descending → the model's default order.
 * Only one column is sorted from the UI; the server appends the primary key tiebreaker.
 */
export function cycleSort(
  search: ListSearch,
  field: string,
  defaultSort: readonly string[],
): ListSearch {
  const { sort: _sort, ...rest } = firstPage(search);
  const [primary] = parseSort(search.sort, defaultSort);
  if (primary?.field !== field) return { ...rest, sort: field };
  if (!primary.desc) return { ...rest, sort: `-${field}` };
  return rest;
}

function isFilterKey(key: string): key is FilterKey {
  return key.startsWith(FILTER_PREFIX) && key.length > FILTER_PREFIX.length;
}
