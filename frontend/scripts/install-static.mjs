// Copy dist/ into the Python package (src/oneadmin/static) with its source stamp, exactly as
// the hatch build hook does, so an editable install (`uv sync`) serves the UI just built.

import { execFileSync } from "node:child_process";
import { cpSync, rmSync, writeFileSync } from "node:fs";

const root = new URL("../..", import.meta.url).pathname;
const target = `${root}src/oneadmin/static`;
rmSync(target, { recursive: true, force: true });
cpSync(new URL("../dist", import.meta.url).pathname, target, { recursive: true });
// The same hash the hook computes (hatch_build.source_hash), so `uv build` reuses this build.
const hash = execFileSync(
  "uv",
  [
    "run",
    "--no-sync",
    "--with",
    "hatchling",
    "python",
    "-c",
    "import hatch_build, pathlib; print(hatch_build.source_hash(pathlib.Path('frontend')))",
  ],
  { cwd: root, encoding: "utf8" },
).trim();
writeFileSync(`${target}/.source-hash`, `${hash}\n`);
console.log(`installed UI into ${target}`);
