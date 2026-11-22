/**
 * The whole app (router, query cache, pages) against an in-memory API: the user-visible flows
 * of M4 without a browser. The real-server equivalent is the Playwright smoke test.
 */
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App, createApp } from "@/app";
import type { AppConfig } from "@/config";
import { installFakeApi } from "@/test/fakeApi";

const config: AppConfig = {
  basePath: "/admin",
  apiBase: "/admin/api/v1",
  title: "Test Site",
  auth: "builtin",
  dev: false,
};

function renderAt(path: string) {
  const app = createApp(config, {
    history: createMemoryHistory({ initialEntries: [`/admin${path}`] }),
  });
  render(<App app={app} />);
  return app;
}

describe("signing in", () => {
  it("sends a signed-out visitor to the login page and back after signing in", async () => {
    const api = installFakeApi({ signedIn: false });
    const { router } = renderAt("/m/posts?sort=title");
    const user = userEvent.setup();

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Email"), "root@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");

    await user.type(screen.getByLabelText("Password"), "right password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Posts" });
    expect(router.state.location.href).toBe("/m/posts?sort=title");
    expect(api.log).toContain("GET /models/posts/rows?sort=title&count=true");
  });

  it("signs out with the CSRF token and returns to the login page", async () => {
    const api = installFakeApi();
    renderAt("/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
    const logout = api.fetch.mock.calls.find(([url]) => String(url).endsWith("/auth/logout"));
    const init = logout?.[1] as RequestInit | undefined;
    expect(init?.headers).toMatchObject({ "x-csrf-token": "csrf-1" });
  });
});

describe("dev mode", () => {
  it("offers first-run setup while no admin exists, then signs in", async () => {
    const api = installFakeApi({ signedIn: false });
    api.setupNeeded = true;
    const app = createApp(
      { ...config, dev: true },
      { history: createMemoryHistory({ initialEntries: ["/admin/m/posts"] }) },
    );
    render(<App app={app} />);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Create the first admin account" });
    expect(screen.getByText("Dev")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "me@example.com");
    await user.type(screen.getByLabelText("Password"), "a long password");
    await user.type(screen.getByLabelText("Password (again)"), "a different one");
    await user.type(screen.getByLabelText("Setup token"), "local-test-token");
    await user.click(screen.getByRole("button", { name: "Create account and sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The passwords don't match.");
    expect(api.log).not.toContain("POST /auth/setup");

    await user.clear(screen.getByLabelText("Password (again)"));
    await user.type(screen.getByLabelText("Password (again)"), "a long password");
    await user.click(screen.getByRole("button", { name: "Create account and sign in" }));
    await screen.findByRole("heading", { name: "Posts" });
    expect(app.router.state.location.href).toBe("/m/posts");
  });

  it("shows the normal sign-in once an admin exists", async () => {
    installFakeApi({ signedIn: false });
    const app = createApp(
      { ...config, dev: true },
      { history: createMemoryHistory({ initialEntries: ["/admin/login"] }) },
    );
    render(<App app={app} />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("list", () => {
  it("renders rows, relation labels, booleans and the count", async () => {
    installFakeApi();
    renderAt("/m/posts");
    const table = await screen.findByRole("table", { name: "Posts" });
    const [, first, second] = within(table).getAllByRole("row");
    expect(
      within(first as HTMLElement).getByRole("link", { name: "ada@example.com" }),
    ).toHaveAttribute("href", "/admin/m/users/r/1");
    // An out-of-scope relation (label null) is shown without a link.
    expect(within(second as HTMLElement).queryByRole("link", { name: /#9/ })).toBeNull();
    expect(within(second as HTMLElement).getByText("#9")).toBeInTheDocument();
    expect(within(first as HTMLElement).getByText("Yes")).toBeInTheDocument();
    expect(await screen.findByText("3 rows")).toBeInTheDocument();
    expect(screen.getByTestId("page-range")).toHaveTextContent("Showing 1–2 of 3 rows");
  });

  it("marks the sorted column and links headers to the next sort", async () => {
    installFakeApi();
    renderAt("/m/posts");
    const id = await screen.findByRole("columnheader", { name: /^Id/ });
    expect(id).toHaveAttribute("aria-sort", "descending");
    expect(within(id).getByRole("link")).toHaveAttribute("href", "/admin/m/posts");
    const title = screen.getByRole("columnheader", { name: /^Title/ });
    expect(title).not.toHaveAttribute("aria-sort");
    expect(within(title).getByRole("link")).toHaveAttribute("href", "/admin/m/posts?sort=title");
  });

  it("pages with cursors and doesn't recount on later pages", async () => {
    const api = installFakeApi();
    renderAt("/m/posts");
    const user = userEvent.setup();
    await screen.findByText("Third");
    expect(screen.getByTestId("page-range")).toHaveTextContent("Showing 1–2 of 3 rows");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await user.click(screen.getByRole("link", { name: "Next page" }));
    await screen.findByText("First");
    expect(screen.getByTestId("page-range")).toHaveTextContent("Showing 3–3 of 3 rows");
    expect(screen.getByRole("link", { name: "Previous page" })).toHaveAttribute(
      "href",
      "/admin/m/posts?cursor=page-1&start=1",
    );
    expect(api.log).toContain("GET /models/posts/rows?cursor=page-2&count=false");
    expect(screen.getByText("3 rows")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Last page" })).toBeDisabled();
  });

  it("debounces search into the URL and the API query", async () => {
    const api = installFakeApi();
    const { router } = renderAt("/m/posts");
    const user = userEvent.setup();
    await user.type(await screen.findByRole("searchbox", { name: "Search Posts" }), "thi");
    await screen.findByText("Third");
    await expect.poll(() => router.state.location.href).toBe("/m/posts?q=thi");
    expect(api.log.filter((l) => l.includes("q=")).length).toBe(1);
  });

  it("adds a filter from the popover and removes it from its chip", async () => {
    const api = installFakeApi();
    const { router } = renderAt("/m/posts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add filter" }));
    await user.selectOptions(screen.getByLabelText("Value"), "false");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await expect.poll(() => router.state.location.href).toBe("/m/posts?f.published__eq=false");
    expect(api.log).toContain("GET /models/posts/rows?f.published__eq=false&count=true");
    await user.click(screen.getByRole("link", { name: "Remove filter: Published is No" }));
    await expect.poll(() => router.state.location.href).toBe("/m/posts");
  });
});

describe("detail", () => {
  it("shows every field with the relation linked, and a breadcrumb back to the list view", async () => {
    installFakeApi();
    renderAt("/m/posts?sort=title");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "2" }));
    await screen.findByRole("heading", { name: "Second" });
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(breadcrumb).getByRole("link", { name: "Posts" })).toHaveAttribute(
      "href",
      "/admin/m/posts?sort=title",
    );
    expect(screen.getByText("Author")).toBeInTheDocument();
  });

  it("explains a missing row", async () => {
    installFakeApi();
    renderAt("/m/posts/r/404");
    expect(await screen.findByText("Post not found")).toBeInTheDocument();
  });

  it("shows the not-found page for an unknown model", async () => {
    installFakeApi();
    renderAt("/m/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});
