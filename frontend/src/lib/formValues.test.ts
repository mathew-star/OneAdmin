import { describe, expect, it } from "vitest";
import type { FieldSchema } from "@/api/types";
import {
  blankDrafts,
  buildPayload,
  changedFields,
  fromDraft,
  initialDrafts,
  toDraft,
} from "./formValues";

const field = (overrides: Partial<FieldSchema>): FieldSchema => ({
  name: "x",
  label: "X",
  kind: "string",
  nullable: false,
  primary_key: false,
  sortable: true,
  filter_ops: [],
  enum_values: null,
  max_length: null,
  tz_aware: false,
  writable: true,
  required: false,
  ...overrides,
  widget: overrides.widget ?? overrides.kind ?? "string",
});

describe("toDraft", () => {
  it("uses checkboxes for NOT NULL booleans and selects for nullable ones", () => {
    expect(toDraft(field({ kind: "boolean" }), true)).toBe(true);
    expect(toDraft(field({ kind: "boolean" }), null)).toBe(false);
    expect(toDraft(field({ kind: "boolean", nullable: true }), false)).toBe("false");
    expect(toDraft(field({ kind: "boolean", nullable: true }), null)).toBe("");
  });

  it("keeps decimals and big integers as strings", () => {
    expect(toDraft(field({ kind: "decimal" }), "12.50")).toBe("12.50");
    expect(toDraft(field({ kind: "integer" }), "9007199254740993")).toBe("9007199254740993");
  });

  it("formats datetimes for datetime-local inputs", () => {
    expect(toDraft(field({ kind: "datetime" }), "2026-11-06T09:30:00.123456")).toBe(
      "2026-11-06T09:30:00",
    );
    const local = toDraft(field({ kind: "datetime", tz_aware: true }), "2026-11-06T09:30:00+00:00");
    expect(new Date(String(local)).toISOString()).toBe("2026-11-06T09:30:00.000Z");
  });
});

describe("fromDraft", () => {
  it("sends safe integers as numbers and unsafe ones as strings", () => {
    expect(fromDraft(field({ kind: "integer" }), "42")).toBe(42);
    expect(fromDraft(field({ kind: "integer" }), "9007199254740993")).toBe("9007199254740993");
    expect(fromDraft(field({ kind: "integer" }), "4x2")).toBe("4x2"); // the server explains
  });

  it("sends decimals as strings and floats as numbers", () => {
    expect(fromDraft(field({ kind: "decimal" }), " 1.10 ")).toBe("1.10");
    expect(fromDraft(field({ kind: "float" }), "1.5")).toBe(1.5);
  });

  it("converts local datetimes to UTC for tz-aware columns only", () => {
    expect(fromDraft(field({ kind: "datetime", tz_aware: true }), "2026-11-06T10:00")).toBe(
      new Date("2026-11-06T10:00").toISOString(),
    );
    expect(fromDraft(field({ kind: "datetime" }), "2026-11-06T10:00")).toBe("2026-11-06T10:00");
  });

  it("keeps whitespace in text but not in other kinds", () => {
    expect(fromDraft(field({ kind: "text" }), "  hi ")).toBe("  hi ");
    expect(fromDraft(field({ kind: "uuid" }), "  abc ")).toBe("abc");
  });
});

describe("buildPayload", () => {
  const fields = [
    field({ name: "title", required: true }),
    field({ name: "notes", kind: "text", nullable: true }),
    field({ name: "total", kind: "decimal" }),
    field({ name: "published", kind: "boolean" }),
    field({ name: "id", kind: "integer", writable: false }),
  ];

  it("create: omits blanks so defaults apply and required fields are reported", () => {
    const drafts = { ...blankDrafts(fields), total: "5.00" };
    expect(buildPayload("create", fields, blankDrafts(fields), drafts)).toEqual({
      total: "5.00",
      published: false,
    });
  });

  it("update: sends only changed fields, with null for a cleared nullable field", () => {
    const initial = initialDrafts(fields, {
      title: "A",
      notes: "n",
      total: "1.00",
      published: true,
      id: 1,
    });
    const drafts = { ...initial, notes: "", published: false };
    expect(changedFields(initial, drafts)).toEqual(["notes", "published"]);
    expect(buildPayload("update", fields, initial, drafts)).toEqual({
      notes: null,
      published: false,
    });
  });

  it("update: a cleared NOT NULL text becomes an empty string; other kinds become null", () => {
    const initial = initialDrafts(fields, { title: "A", total: "1.00" });
    expect(buildPayload("update", fields, initial, { ...initial, title: "", total: "" })).toEqual({
      title: "",
      total: null,
    });
  });

  it("never sends read-only fields", () => {
    const initial = initialDrafts(fields, { id: 1 });
    expect(buildPayload("update", fields, initial, { ...initial, id: "2" })).toEqual({});
  });
});
