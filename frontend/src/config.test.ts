import { describe, expect, it, vi } from "vitest";
import { readConfig } from "./config";

function docWith(json: string | null): Document {
  const doc = document.implementation.createHTMLDocument();
  if (json !== null) {
    const node = doc.createElement("script");
    node.type = "application/json";
    node.id = "oneadmin-config";
    node.textContent = json;
    doc.head.append(node);
  }
  return doc;
}

describe("readConfig", () => {
  it("reads the server-injected block", () => {
    const config = {
      basePath: "/backoffice",
      apiBase: "/backoffice/api/v1",
      title: "Shop",
      auth: "external",
    };
    expect(readConfig(docWith(JSON.stringify(config)))).toEqual({ ...config, dev: false });
    expect(readConfig(docWith(JSON.stringify({ ...config, dev: true }))).dev).toBe(true);
  });

  it("falls back to development defaults", () => {
    expect(readConfig(docWith(null)).basePath).toBe("/admin");
  });

  it("rejects malformed config loudly", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(readConfig(docWith('{"basePath": 1}')).basePath).toBe("/admin");
    expect(readConfig(docWith("not json")).basePath).toBe("/admin");
    expect(error).toHaveBeenCalledTimes(2);
  });
});
