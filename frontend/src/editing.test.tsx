/**
 * The editing flows of M6 against the in-memory API: what is sent, what is shown, and
 * that nothing is lost on conflicts. The real-server equivalent is the Playwright test.
 */
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { queryKeys } from "@/api/queries";
import { App, createApp } from "@/app";
import type { AppConfig } from "@/config";
import { installFakeApi, VIEW_ONLY } from "@/test/fakeApi";

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

function sent(api: ReturnType<typeof installFakeApi>, method: string) {
  const call = api.fetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === method)
    .at(-1);
  const init = call?.[1] as RequestInit | undefined;
  return {
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
    headers: (init?.headers ?? {}) as Record<string, string>,
  };
}

describe("permissions", () => {
  it("hides every edit control from view-only users", async () => {
    installFakeApi({ permissions: VIEW_ONLY });
    renderAt("/m/posts");
    await screen.findByRole("table", { name: "Posts" });
    expect(screen.queryByRole("link", { name: /Add post/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    await userEvent.setup().click(screen.getByRole("link", { name: "3" }));
    await screen.findByRole("heading", { name: "Third" });
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("editing", () => {
  it("keeps unsaved input when the row refetches in the background", async () => {
    const api = installFakeApi();
    const { queryClient } = renderAt("/m/posts/r/3/edit");
    const user = userEvent.setup();
    const title = await screen.findByLabelText(/^Title/);
    await user.clear(title);
    await user.type(title, "My unfinished title");
    api.editElsewhere(3, { published: false });

    await queryClient.invalidateQueries({ queryKey: queryKeys.row("posts", "3") });
    await waitFor(() => expect(screen.getByLabelText(/^Title/)).toHaveValue("My unfinished title"));
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
  });

  it("sends only the changed fields with the row's version", async () => {
    const api = installFakeApi();
    const { router } = renderAt("/m/posts/r/3/edit");
    const user = userEvent.setup();
    const title = await screen.findByLabelText(/^Title/);
    await user.clear(title);
    await user.type(title, "Third, edited");
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("heading", { name: "Third, edited" });
    expect(router.state.location.pathname).toBe("/m/posts/r/3");
    expect(sent(api, "PATCH")).toEqual({
      body: { title: "Third, edited" },
      headers: expect.objectContaining({ "if-match": "v1", "x-csrf-token": "csrf-1" }),
    });
    expect(await screen.findByText("Changes saved.")).toBeInTheDocument();
  });

  it("shows server validation errors next to their fields", async () => {
    const api = installFakeApi();
    renderAt("/m/posts/r/3/edit");
    const user = userEvent.setup();
    const title = await screen.findByLabelText(/^Title/);
    await user.type(title, "!");
    api.failNextWith = { title: "must be at most 200 characters" };
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Please fix 1 field")).toBeInTheDocument();
    expect(title).toHaveAttribute("aria-invalid", "true");
    expect(title).toHaveAccessibleDescription("must be at most 200 characters");
  });

  it("on a conflict, rebases onto the latest version and keeps the user's edits", async () => {
    const api = installFakeApi();
    renderAt("/m/posts/r/3/edit");
    const user = userEvent.setup();
    const title = await screen.findByLabelText(/^Title/);
    await user.clear(title);
    await user.type(title, "Mine");
    api.editElsewhere(3, { published: false }); // someone else, meanwhile

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Someone else changed this row while you were editing"),
    ).toBeInTheDocument();
    expect(screen.getByText(/They changed: Published\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Use the latest version, keep my changes" }),
    );
    expect(screen.getByLabelText(/^Title/)).toHaveValue("Mine");
    expect(screen.getByLabelText("Published")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("heading", { name: "Mine" });
    expect(sent(api, "PATCH")).toEqual({
      body: { title: "Mine" },
      headers: expect.objectContaining({ "if-match": "v2" }),
    });
    expect(api.posts.find((p) => p.id === 3)).toMatchObject({ title: "Mine", published: false });
  });
});

describe("creating", () => {
  it("creates from the list's Add button and picks a relation by label", async () => {
    const api = installFakeApi();
    const { router } = renderAt("/m/posts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "Add post" }));
    await user.type(await screen.findByLabelText(/^Title/), "Brand new");
    await user.click(screen.getByRole("combobox", { name: /^Author/ }));
    await user.click(await screen.findByRole("option", { name: /bob@example.com/ }));
    await user.click(screen.getByRole("button", { name: "Create post" }));
    await screen.findByRole("heading", { name: "Brand new" });
    expect(router.state.location.pathname).toBe("/m/posts/r/4");
    expect(sent(api, "POST").body).toEqual({ title: "Brand new", published: false, author_id: 2 });
  });

  it("marks required fields", async () => {
    installFakeApi();
    renderAt("/m/posts/new");
    expect(await screen.findByLabelText(/^Title/)).toHaveAttribute("aria-required", "true");
    expect(screen.getByLabelText("Published")).not.toHaveAttribute("aria-required");
  });
});

describe("deleting and actions", () => {
  it("deletes after confirmation, with the version", async () => {
    const api = installFakeApi();
    const { router } = renderAt("/m/posts/r/2");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete Second?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await screen.findByText("Post deleted.");
    expect(router.state.location.pathname).toBe("/m/posts");
    expect(sent(api, "DELETE").headers).toMatchObject({ "if-match": "v1" });
    expect(api.posts.map((p) => p.id)).toEqual([3, 1]);
  });

  it("runs a bulk action on the selected rows", async () => {
    const api = installFakeApi();
    renderAt("/m/posts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: "Select row 2" }));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    expect(within(bar).getByText("1 post selected")).toBeInTheDocument();
    await user.selectOptions(within(bar).getByLabelText("Action"), "publish");
    await user.click(within(bar).getByRole("button", { name: "Run" }));
    expect(await screen.findByText("Published 1.")).toBeInTheDocument();
    expect(sent(api, "POST").body).toEqual({ pks: ["2"] });
    expect(screen.queryByRole("region", { name: "Bulk actions" })).toBeNull();
  });

  it("asks before destructive actions; select-page selects every row", async () => {
    const api = installFakeApi();
    renderAt("/m/posts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: "Select all rows on this page" }));
    await user.click(screen.getByRole("button", { name: "Run" })); // "Delete selected" is first
    const dialog = await screen.findByRole("alertdialog", { name: "Delete selected: 2 posts?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete selected" }));
    await screen.findByText("Delete selected: done for 2 posts.");
    expect(api.posts.map((p) => p.id)).toEqual([1]);
  });
});

describe("history", () => {
  it("lists audit entries with before and after values", async () => {
    const api = installFakeApi();
    renderAt("/m/posts/r/3/edit");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/^Title/), "!");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("heading", { name: "Third!" });
    await user.click(screen.getByRole("button", { name: "Show changes" }));
    const table = await screen.findByRole("table", { name: "Changed fields" });
    expect(within(table).getByRole("row", { name: "Title Third Third!" })).toBeInTheDocument();
    expect(api.log).toContain("GET /models/posts/rows/3/history");
  });
});
