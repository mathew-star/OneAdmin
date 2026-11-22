/**
 * Query-string (de)serialisation for the router.
 *
 * TanStack Router's default encodes search values as JSON, so `?f.id__eq=5` would arrive as
 * the number 5 and `?f.name__eq=true` as a boolean. The admin's search params are forwarded
 * to the API verbatim and parsed there per column type, so they must stay plain strings in a
 * flat, readable `a=1&b=2` form.
 */
export function parseSearch(search: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(search)) out[key] = value;
  return out;
}

export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
