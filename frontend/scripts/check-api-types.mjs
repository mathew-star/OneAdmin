// Fail if src/api/openapi.d.ts is out of date with openapi.json (CLAUDE.md invariant 11).
// openapi.json itself is checked against the Python contract by
// tests/unit/test_openapi_snapshot.py, so together the chain Pydantic → JSON → TS is guarded.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const dir = mkdtempSync(join(tmpdir(), "oneadmin-api-"));
try {
  const out = join(dir, "openapi.d.ts");
  execFileSync("pnpm", ["exec", "openapi-typescript", "openapi.json", "-o", out], {
    cwd: root,
    stdio: "ignore",
  });
  const committed = readFileSync(join(root, "src/api/openapi.d.ts"), "utf8");
  if (committed !== readFileSync(out, "utf8")) {
    console.error("src/api/openapi.d.ts is stale: run `pnpm gen:api`");
    process.exit(1);
  }
  console.log("API types are up to date");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
