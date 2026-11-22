/**
 * Validate the `?next=` target after login. Only in-app paths are allowed, so a crafted link
 * like `/admin/login?next=https://evil.example` can't turn the login page into an open
 * redirect. Paths are router paths (without the mount prefix).
 */
export function safeNext(next: unknown): string {
  if (typeof next !== "string") return "/";
  // "//host" and "/\host" are protocol-relative URLs in browsers.
  if (!next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  if ([...next].some((ch) => ch.charCodeAt(0) < 0x20)) return "/";
  if (next === "/login" || next.startsWith("/login?")) return "/";
  return next;
}
