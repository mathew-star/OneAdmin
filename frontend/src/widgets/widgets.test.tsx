import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FieldSchema } from "@/api/types";
import { App, createApp } from "@/app";
import { installFakeApi } from "@/test/fakeApi";
import { formatMoney, registerBuiltinWidgets } from "./builtin";
import { WidgetRegistry } from "./registry";

const Mine = () => null;

const field = (widget: string, extra: Partial<FieldSchema> = {}): FieldSchema => ({
  name: "x",
  label: "X",
  kind: "string",
  widget,
  nullable: true,
  primary_key: false,
  sortable: false,
  filter_ops: [],
  enum_values: null,
  max_length: null,
  tz_aware: false,
  writable: true,
  required: false,
  ...extra,
});

describe("WidgetRegistry", () => {
  it("returns null for unknown widgets, so the kind's rendering is used", () => {
    const registry = registerBuiltinWidgets(new WidgetRegistry());
    expect(registry.cell(field("email"))).not.toBeNull();
    expect(registry.cell(field("from-a-newer-server"))).toBeNull();
    expect(registry.input(field("string"))).toBeNull();
  });

  it("lets a later registration replace a built-in", () => {
    const registry = registerBuiltinWidgets(new WidgetRegistry()).registerCell("email", Mine);
    expect(registry.cell(field("email"))).toBe(Mine);
  });
});

describe("built-in widgets", () => {
  const registry = registerBuiltinWidgets(new WidgetRegistry());
  const renderCell = (f: FieldSchema, value: unknown) => {
    const Cell = registry.cell(f);
    if (!Cell) throw new Error("no cell");
    return render(<Cell field={f} value={value} full={false} />);
  };

  it("links http(s) URLs to a new tab, and never anything else", () => {
    renderCell(field("url"), "https://example.com/a");
    const link = screen.getByRole("link", { name: /example\.com\/a/ });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");

    renderCell(field("url"), "javascript:alert(1)");
    expect(screen.queryByRole("link", { name: /alert/ })).toBeNull();
    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
  });

  it("formats money with its currency, keeping every digit", () => {
    expect(formatMoney("1234.5", "EUR", "en-US")).toBe("€1,234.50");
    expect(formatMoney("12345678901234567.89", "USD", "en-US")).toBe("$12,345,678,901,234,567.89");
    renderCell(field("money", { kind: "decimal", widget_options: { currency: "EUR" } }), "9.99");
    expect(screen.getByText(/9\.99/)).toBeInTheDocument();
  });
});

describe("in the app", () => {
  it("renders an email field as a mailto link", async () => {
    installFakeApi();
    const app = createApp(
      { basePath: "/admin", apiBase: "/admin/api/v1", title: "T", auth: "builtin", dev: false },
      { history: createMemoryHistory({ initialEntries: ["/admin/m/users"] }) },
    );
    render(<App app={app} />);
    const link = await screen.findByRole("link", { name: "ada@example.com" });
    expect(link).toHaveAttribute("href", "mailto:ada@example.com");
  });
});
