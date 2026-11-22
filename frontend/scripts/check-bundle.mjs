// Post-build checks for dist/ (run by `pnpm build`):
//
// 1. Initial JavaScript (the entry chunk and what it statically imports) stays within the
//    budget of ADR-0011: 150 KB gzip. Lazily loaded chunks don't count.
// 2. index.html has no inline <script> or <style>: the admin's CSP is
//    `script-src 'self'; style-src 'self'`, so inline code would simply not run.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 150 * 1024;
const dist = new URL("../dist/", import.meta.url).pathname;
const html = readFileSync(join(dist, "index.html"), "utf8");
const failures = [];

for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
  const [, attrs, body] = match;
  if (!/\bsrc=/.test(attrs) && body.trim())
    failures.push(`inline <script> in index.html: ${body.slice(0, 60)}`);
}
if (/<style\b/.test(html)) failures.push("inline <style> in index.html");
if (/\sstyle="/.test(html)) failures.push('inline style="" attribute in index.html');

// Entry scripts and modulepreloads referenced by index.html, plus their static imports.
const referenced = [...html.matchAll(/(?:src|href)="\.\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]);
const seen = new Set();
const queue = [...referenced];
while (queue.length) {
  const file = queue.shift();
  if (seen.has(file)) continue;
  seen.add(file);
  const code = readFileSync(join(dist, file), "utf8");
  // Static imports between chunks look like `from"./chunk-abc.js"` / `import"./x.js"`.
  for (const m of code.matchAll(/(?:from|import)\s*"\.\/([^"]+\.js)"/g))
    queue.push(`assets/${m[1]}`);
}

let total = 0;
for (const file of seen) total += gzipSync(readFileSync(join(dist, file))).length;
const css = readdirSync(join(dist, "assets")).filter((f) => f.endsWith(".css"));
const cssBytes = css.reduce(
  (sum, f) => sum + gzipSync(readFileSync(join(dist, "assets", f))).length,
  0,
);

const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
console.log(
  `initial JS: ${kb(total)} gzip (${seen.size} file(s), budget ${kb(BUDGET_BYTES)}); CSS: ${kb(cssBytes)} gzip`,
);
if (total > BUDGET_BYTES)
  failures.push(`initial JS ${kb(total)} exceeds the ${kb(BUDGET_BYTES)} budget`);
if (seen.size === 0) failures.push("no entry script found in index.html");

if (failures.length) {
  for (const f of failures) console.error(`check-bundle: ${f}`);
  process.exit(1);
}
