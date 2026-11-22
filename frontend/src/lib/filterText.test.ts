import { describe, expect, it } from "vitest";
import type { FieldSchema } from "@/api/types";
import { describeFilter, opLabel, toWireValue } from "./filterText";

const field = (overrides: Partial<FieldSchema>): FieldSchema => ({
  name: "x",
  label: "X",
  kind: "string",
  nullable: false,
  primary_key: false,
  sortable: true,
  filter_ops: ["eq"],
  enum_values: null,
  max_length: null,
  tz_aware: false,
  writable: false,
  required: false,
  ...overrides,
  widget: overrides.widget ?? overrides.kind ?? "string",
});

describe("opLabel", () => {
  it("words ordered operators by kind", () => {
    expect(opLabel("gte", field({ kind: "date" }))).toBe("on or after");
    expect(opLabel("gte", field({ kind: "integer" }))).toBe("≥");
    expect(opLabel("icontains")).toBe("contains (any case)");
  });
});

describe("describeFilter", () => {
  it("reads naturally", () => {
    const published = field({ name: "published", label: "Published", kind: "boolean" });
    expect(
      describeFilter(
        { key: "f.published__eq", field: "published", op: "eq", value: "true" },
        published,
      ),
    ).toBe("Published is Yes");
    const shipped = field({ label: "Shipped at", kind: "datetime", nullable: true });
    expect(
      describeFilter({ key: "f.x__isnull", field: "x", op: "isnull", value: "false" }, shipped),
    ).toBe("Shipped at is not empty");
    expect(
      describeFilter(
        { key: "f.s__in", field: "s", op: "in", value: "a,b" },
        field({ label: "Status" }),
      ),
    ).toBe("Status is one of a, b");
  });

  it("falls back to the raw field name for unknown fields", () => {
    expect(
      describeFilter({ key: "f.gone__eq", field: "gone", op: "eq", value: "1" }, undefined),
    ).toBe("gone is 1");
  });
});

describe("toWireValue", () => {
  it("normalises 'in' lists", () => {
    expect(toWireValue(field({}), "in", " a , ,b ")).toBe("a,b");
  });

  it("sends tz-aware datetimes as UTC and naive ones as typed", () => {
    const local = "2026-11-06T12:00";
    expect(toWireValue(field({ kind: "datetime", tz_aware: true }), "gte", local)).toBe(
      new Date(local).toISOString(),
    );
    expect(toWireValue(field({ kind: "datetime" }), "gte", local)).toBe(local);
  });
});
