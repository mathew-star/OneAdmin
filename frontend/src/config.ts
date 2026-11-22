/**
 * Runtime configuration injected by the server into `index.html` as an inert JSON block
 * (`<script type="application/json" id="oneadmin-config">`). JSON rather than inline JS keeps
 * the admin's strict CSP (`script-src 'self'`) intact. See `oneadmin/ui/spa.py`.
 */
export interface AppConfig {
  /** Where the admin is mounted, e.g. `/admin`. `/` when mounted at the root. */
  basePath: string;
  /** Absolute path of the JSON API, e.g. `/admin/api/v1`. */
  apiBase: string;
  /** Site title from `AdminSite(title=...)`, shown before the schema has loaded. */
  title: string;
  /**
   * `builtin`: OneAdmin's own login page and sessions. `external`: a custom `AuthBackend`
   * authenticates requests (e.g. the host app's SSO), so the UI has no login form.
   */
  auth: "builtin" | "external";
  /** Development mode: loopback only, first-run setup on the login page, a visible badge. */
  dev: boolean;
}

/** Used by the Vite dev server, where no server-side injection happens. */
const DEV_DEFAULTS: AppConfig = {
  basePath: "/admin",
  apiBase: "/admin/api/v1",
  title: "OneAdmin",
  auth: "builtin",
  dev: false,
};

export function readConfig(doc: Document = document): AppConfig {
  const node = doc.getElementById("oneadmin-config");
  if (!node?.textContent) return DEV_DEFAULTS;
  try {
    const raw: unknown = JSON.parse(node.textContent);
    if (isConfig(raw)) return { ...raw, dev: raw.dev === true };
  } catch {
    // Fall through: a malformed block is a server bug; the dev defaults are the safest guess.
  }
  console.error("oneadmin: invalid #oneadmin-config block; using defaults");
  return DEV_DEFAULTS;
}

function isConfig(value: unknown): value is Omit<AppConfig, "dev"> & { dev?: boolean } {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.basePath === "string" &&
    typeof v.apiBase === "string" &&
    typeof v.title === "string" &&
    (v.auth === "builtin" || v.auth === "external") &&
    (v.dev === undefined || typeof v.dev === "boolean")
  );
}
