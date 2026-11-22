/**
 * The M6 editing journey in a real browser against tests/e2e/server.py:
 * create (with a relation picked by label) → edit → a conflict from a second tab →
 * bulk action → history → delete. It creates its own rows and removes them again, so the
 * read-only journey (smoke.spec.ts) sees the seeded data unchanged.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function signIn(page: Page) {
  await page.goto("login");
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("e2e password 1234");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function expectAccessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

async function createPost(page: Page, title: string) {
  await page.goto("m/posts");
  await page.getByRole("link", { name: "Add post" }).click();
  await page.getByLabel(/^Title/).fill(title);
  await page.getByLabel(/^Created at/).fill("2026-11-06T10:00:00");
  await page.getByRole("combobox", { name: /^Author/ }).click();
  await page.getByRole("combobox", { name: /^Author/ }).fill("Author 03");
  await page.getByRole("option", { name: /Author 03/ }).click();
  await page.getByRole("button", { name: "Create post" }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  return page.url();
}

test("create, edit, resolve a conflict, act, read history, delete", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);

  // Create: a required field left empty is reported by the server, next to the field.
  await page.goto("m/posts/new");
  await expect(page.getByLabel(/^Title/)).toHaveAttribute("aria-required", "true");
  await expectAccessible(page);
  await page.getByRole("button", { name: "Create post" }).click();
  await expect(page.getByText(/Please fix \d fields/)).toBeVisible();
  await expect(page.getByLabel(/^Title/)).toHaveAttribute("aria-invalid", "true");

  const detailUrl = await createPost(page, "E2E draft");
  await expect(page.getByRole("link", { name: "Author 03" })).toBeVisible();
  await expect(page.getByText("Post created.")).toBeVisible();

  // Edit in this tab...
  await page.getByRole("link", { name: "Edit" }).click();
  await expect(
    page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "E2E draft" }),
  ).toHaveAttribute("href", new URL(detailUrl).pathname);
  await page.getByLabel(/^Title/).fill("E2E draft, edited here");
  await expectAccessible(page);

  // ...while a second tab changes the same post.
  const other = await context.newPage();
  await other.goto(`${detailUrl}/edit`);
  await other.getByLabel("Published").check();
  await other.getByRole("button", { name: "Save changes" }).click();
  await expect(other.getByText("Changes saved.")).toBeVisible();
  await other.close();

  // Saving here is refused rather than silently overwriting; rebase keeps our edit.
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByText("Someone else changed this row while you were editing"),
  ).toBeVisible();
  await expect(page.getByText(/They changed: Published\./)).toBeVisible();
  await page.getByRole("button", { name: "Use the latest version, keep my changes" }).click();
  await expect(page.getByLabel("Published")).toBeChecked();
  await expect(page.getByLabel(/^Title/)).toHaveValue("E2E draft, edited here");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "E2E draft, edited here" }),
  ).toBeVisible();

  // History records both edits.
  await page.getByRole("button", { name: "Show changes" }).click();
  await expect(page.getByRole("table", { name: "Changed fields" })).toHaveCount(3); // create + 2 updates
  await expectAccessible(page);

  // Bulk action on our two rows (found by search), with its confirmation.
  await createPost(page, "E2E second");
  await page.goto("m/posts?q=E2E");
  await page.getByRole("checkbox", { name: "Select all rows on this page" }).check();
  const bar = page.getByRole("region", { name: "Bulk actions" });
  await expect(bar.getByText("2 posts selected")).toBeVisible();
  await bar.getByLabel("Action").selectOption({ label: "Publish" });
  await bar.getByRole("button", { name: "Run" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByText("Publish the selected posts?")).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published 2 post(s).")).toBeVisible();

  // Delete both again (bulk), leaving the seeded data as it was.
  await page.getByRole("checkbox", { name: "Select all rows on this page" }).check();
  await bar.getByLabel("Action").selectOption({ label: "Delete selected" });
  await bar.getByRole("button", { name: "Run" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete selected" }).click();
  await expect(page.getByText("Deleted 2 posts.")).toBeVisible();
  await expect(page.getByText("No posts match")).toBeVisible();

  expect(errors).toEqual([]);
});

test("a single delete asks first and goes back to the list", async ({ page }) => {
  await signIn(page);
  await createPost(page, "E2E to delete");
  await page.getByRole("button", { name: "Delete" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete E2E to delete?" });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Post deleted.")).toBeVisible();
  await expect(page).toHaveURL(/\/m\/posts/);
});
