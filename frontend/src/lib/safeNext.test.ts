import { describe, expect, it } from "vitest";
import { safeNext } from "./safeNext";

describe("safeNext", () => {
  it.each([
    ["/m/posts?sort=-id", "/m/posts?sort=-id"],
    ["/", "/"],
  ])("allows in-app path %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });

  it.each([
    "https://evil.example",
    "//evil.example/x",
    "/\\evil.example",
    "javascript:alert(1)",
    "m/posts",
    "/login",
    "/login?next=/x",
    "/m/\nposts",
    undefined,
    42,
  ])("rejects %s", (input) => {
    expect(safeNext(input)).toBe("/");
  });
});
