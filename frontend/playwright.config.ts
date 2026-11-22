import { defineConfig, devices } from "@playwright/test";

/**
 * Browser smoke tests against a real OneAdmin app: `tests/e2e/server.py` (SQLite, seeded,
 * built-in login, mounted at /backoffice). The server serves the *packaged* UI from
 * `src/oneadmin/static`, so build it first: `pnpm build:install`.
 */
const PORT = 8765;

export default defineConfig({
  testDir: "e2e",
  // One server and one database for all specs: running them in parallel would let one
  // spec's rows appear in another's assertions.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}/backoffice/`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run python ../tests/e2e/server.py --port ${PORT}`,
    url: `http://localhost:${PORT}/backoffice/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
