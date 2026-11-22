import { describe, expect, it } from "vitest";
import { parseSearch, stringifySearch } from "./searchParams";

describe("search params", () => {
  it("keeps values as strings (no JSON coercion of numbers or booleans)", () => {
    expect(parseSearch("?f.id__eq=5&f.paid__eq=true&f.n__eq=1e3")).toEqual({
      "f.id__eq": "5",
      "f.paid__eq": "true",
      "f.n__eq": "1e3",
    });
  });

  it("round-trips, dropping empty values", () => {
    const qs = stringifySearch({ sort: "-created_at", q: "a&b", cursor: undefined, empty: "" });
    expect(qs).toBe("?sort=-created_at&q=a%26b");
    expect(parseSearch(qs)).toEqual({ sort: "-created_at", q: "a&b" });
    expect(stringifySearch({})).toBe("");
  });
});
