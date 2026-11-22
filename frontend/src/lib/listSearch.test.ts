import { describe, expect, it } from "vitest";
import {
  activeFilters,
  cycleSort,
  filterKey,
  firstPage,
  matchSignature,
  parseListSearch,
  parseSort,
  splitFilterKey,
  toApiQuery,
  withFilter,
  withoutFilter,
  withSearch,
} from "./listSearch";

describe("parseListSearch", () => {
  it("keeps known keys and filters, as strings only", () => {
    expect(
      parseListSearch({
        sort: "-created_at",
        q: "  hello ",
        cursor: "abc",
        last: "1",
        start: "51",
        "f.total__gte": "10",
        evil: "x",
        "f.": "no field",
        count: 5,
      }),
    ).toEqual({
      sort: "-created_at",
      q: "hello",
      cursor: "abc",
      last: "1",
      start: "51",
      "f.total__gte": "10",
    });
  });

  it("drops blank search and non-'1' last", () => {
    expect(parseListSearch({ q: "   ", last: "true", start: "-1" })).toEqual({});
  });
});

describe("filters", () => {
  it("always writes an explicit operator, and splits on the last __", () => {
    expect(filterKey("a__b", "eq")).toBe("f.a__b__eq");
    expect(splitFilterKey("f.a__b__eq")).toEqual({ field: "a__b", op: "eq" });
    expect(splitFilterKey("f.status")).toEqual({ field: "status", op: "eq" });
  });

  it("adding or removing a filter returns to the first page", () => {
    const base = { cursor: "c", last: "1" as const, sort: "id" };
    const added = withFilter(base, "total", "gte", "10");
    expect(added).toEqual({ sort: "id", "f.total__gte": "10" });
    expect(withoutFilter({ ...added, cursor: "c2" }, "f.total__gte")).toEqual({ sort: "id" });
  });

  it("lists active filters", () => {
    expect(activeFilters({ q: "x", "f.paid__eq": "true" })).toEqual([
      { key: "f.paid__eq", field: "paid", op: "eq", value: "true" },
    ]);
  });
});

describe("toApiQuery", () => {
  it("maps the URL onto API parameters one to one", () => {
    expect(
      toApiQuery(
        { sort: "-id", q: "a", cursor: "c", last: "1", start: "51", "f.x__in": "1,2" },
        { count: "false" },
      ),
    ).toEqual({ sort: "-id", q: "a", cursor: "c", last: "true", "f.x__in": "1,2", count: "false" });
  });
});

describe("matchSignature", () => {
  it("ignores order and paging, and is stable across key order", () => {
    const a = matchSignature({ "f.b__eq": "2", "f.a__eq": "1", q: "s", sort: "id", cursor: "c" });
    const b = matchSignature({ q: "s", "f.a__eq": "1", "f.b__eq": "2" });
    expect(a).toBe(b);
    expect(matchSignature({ q: "other" })).not.toBe(a);
  });
});

describe("sorting", () => {
  it("parses the server's sort syntax, falling back to the default", () => {
    expect(parseSort("-created_at,id", [])).toEqual([
      { field: "created_at", desc: true },
      { field: "id", desc: false },
    ]);
    expect(parseSort(undefined, ["-id"])).toEqual([{ field: "id", desc: true }]);
  });

  it("cycles ascending → descending → default, from the first page", () => {
    const asc = cycleSort({ cursor: "c" }, "title", ["-id"]);
    expect(asc).toEqual({ sort: "title" });
    const desc = cycleSort(asc, "title", ["-id"]);
    expect(desc).toEqual({ sort: "-title" });
    expect(cycleSort(desc, "title", ["-id"])).toEqual({});
  });

  it("treats the default order's first key as the active column", () => {
    expect(cycleSort({}, "id", ["id"])).toEqual({ sort: "-id" });
  });
});

describe("withSearch and firstPage", () => {
  it("sets or clears q and drops cursors", () => {
    expect(withSearch({ cursor: "c", sort: "id" }, "  hi ")).toEqual({ sort: "id", q: "hi" });
    expect(withSearch({ q: "hi" }, " ")).toEqual({});
    expect(firstPage({ cursor: "c", last: "1", start: "51", q: "x" })).toEqual({ q: "x" });
  });
});
