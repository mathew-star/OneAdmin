import { describe, expect, it } from "vitest";
import { display, formatCount, formatSeconds, isRelationValue } from "./format";

describe("display", () => {
  it("shows null as empty, whatever the kind", () => {
    expect(display("string", null)).toEqual({ type: "empty" });
    expect(display("integer", undefined)).toEqual({ type: "empty" });
  });

  it("never parses precision-sensitive strings", () => {
    expect(display("decimal", "12345678901234567890.123")).toMatchObject({
      text: "12345678901234567890.123",
      numeric: true,
    });
    expect(display("integer", "9007199254740993")).toMatchObject({ text: "9007199254740993" });
  });

  it("formats booleans, enums and uuids", () => {
    expect(display("boolean", false)).toEqual({ type: "boolean", value: false });
    expect(display("enum", "paid")).toEqual({ type: "badge", text: "paid" });
    expect(display("uuid", "0f8f...")).toMatchObject({ mono: true });
  });

  it("shows naive datetimes as stored, and tz-aware ones in the viewer's zone", () => {
    expect(display("datetime", "2026-11-06T09:30:00.123456")).toMatchObject({
      text: "2026-11-06 09:30:00",
      title: "2026-11-06T09:30:00.123456",
    });
    const aware = display("datetime", "2026-11-06T09:30:00+00:00", {
      tzAware: true,
      locale: "en-GB",
    });
    expect(aware).toMatchObject({ type: "text", title: "2026-11-06T09:30:00+00:00" });
    expect(aware.type === "text" && aware.text).toMatch(/2026/);
  });

  it("formats dates without shifting the calendar day", () => {
    const d = display("date", "2026-01-01", { locale: "en-US" });
    expect(d.type === "text" && d.text).toBe("Jan 1, 2026");
  });

  it("truncates long JSON in lists but not in detail views", () => {
    const value = { items: Array.from({ length: 30 }, (_, i) => i) };
    const short = display("json", value);
    expect(short.type === "text" && short.text.endsWith("…")).toBe(true);
    const full = display("json", value, { full: true });
    expect(full.type === "text" && full.text).toBe(JSON.stringify(value, null, 2));
  });

  it("formats intervals from seconds", () => {
    expect(formatSeconds(90061.5)).toBe("1d 01:01:01.500");
    expect(formatSeconds(-30)).toBe("-00:00:30");
  });
});

describe("isRelationValue", () => {
  it("recognises {pk, label}", () => {
    expect(isRelationValue({ pk: "1", label: null })).toBe(true);
    expect(isRelationValue({ pk: 1, label: "x" })).toBe(false);
    expect(isRelationValue("1")).toBe(false);
  });
});

describe("formatCount", () => {
  it.each([
    [{ value: 1234, exact: true, method: "exact" }, "1,234 rows", "1,234 rows"],
    [{ value: 1, exact: true, method: "capped" }, "1 row", "1 row"],
    [{ value: 0, exact: true, method: "capped" }, "0 rows", "0 rows"],
    [{ value: 10000, exact: false, method: "capped" }, "10,000+ rows", "More than 10,000 rows"],
    [
      { value: 1234567, exact: false, method: "estimate" },
      "≈ 1.2M rows",
      "About 1,234,567 rows (estimated)",
    ],
  ] as const)("%j", (count, short, long) => {
    expect(formatCount(count, "en-US")).toEqual({ short, long });
  });

  it("explains a timed-out count and hides a skipped one", () => {
    expect(formatCount({ value: null, exact: false, method: "timeout" })?.short).toBe("Many rows");
    expect(formatCount({ value: null, exact: false, method: "none" })).toBeNull();
  });
});
