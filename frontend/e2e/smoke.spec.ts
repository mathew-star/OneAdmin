/**
 * The M4 user journey in a real browser against a real server (tests/e2e/server.py):
 * sign in → list → sort → filter → page → detail → back → search → sign out, with axe on
 * every page and zero console errors (which is how CSP violations surface).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const EMAIL = "e2e@example.com";
const PASSWORD = "e2e password 1234";

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    // 401 on /auth/session is how a signed-out visitor is detected; it isn't an error.
    if (message.type() === "error" && !message.text().includes("401")) errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function expectAccessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

async function signIn(page: Page) {
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Wait for the session cookie (we leave the login page) before navigating on.
  await expect(page).not.toHaveURL(/\/login/);
}

test("the full read-only journey", async ({ page }) => {
  const errors = watchConsole(page);

  // A deep link while signed out goes to the login page and comes back afterwards.
  await page.goto("m/posts");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page).toHaveURL(/\/backoffice\/login\?next=/);
  await expect(page).toHaveTitle("E2E Blog");
  await expectAccessible(page);

  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid email or password.");

  await signIn(page);
  await expect(page).toHaveURL(/\/backoffice\/m\/posts$/);
  const table = page.getByRole("table", { name: "Posts" });
  await expect(table.getByRole("row")).toHaveCount(26); // header + 25 per page
  await expect(page.getByText("120 rows", { exact: true })).toBeVisible();
  await expect(page.getByTestId("page-range")).toHaveText("Showing 1–25 of 120 rows");
  await expect(table.getByRole("row").nth(1)).toContainText("Post number 119");
  await expectAccessible(page);

  // Sort by title (ascending).
  await page.getByRole("link", { name: /^Title/ }).click();
  await expect(page).toHaveURL(/sort=title/);
  await expect(page.getByRole("columnheader", { name: /^Title/ })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
  await expect(table.getByRole("row").nth(1)).toContainText("Post number 000");

  // Filter: unpublished only (every third post).
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByLabel("Field").selectOption({ label: "Published" });
  await page.getByLabel("Value").selectOption({ label: "No" });
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/f\.published__eq=false/);
  await expect(page.getByText("40 rows", { exact: true })).toBeVisible();
  await expect(page.getByText("Published is No")).toBeVisible();

  // Page forward and back with cursors.
  await page.getByRole("link", { name: "Next page" }).click();
  await expect(page).toHaveURL(/cursor=/);
  await expect(table.getByRole("row")).toHaveCount(16); // 40 - 25 = 15 rows + header
  await expect(page.getByTestId("page-range")).toHaveText("Showing 26–40 of 40 rows");
  await expect(page.getByRole("button", { name: "Next page" })).toBeDisabled();
  await page.getByRole("link", { name: "Previous page" }).click();
  await expect(table.getByRole("row")).toHaveCount(26);

  // Detail, then back to the same list view via the breadcrumb.
  const listUrl = page.url();
  await table.getByRole("row").nth(1).getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Post number 000");
  await expect(page.getByRole("link", { name: "Author 00" })).toBeVisible();
  await expectAccessible(page);
  await page
    .getByRole("navigation", { name: "Breadcrumb" })
    .getByRole("link", { name: "Posts" })
    .click();
  await expect(page).toHaveURL(listUrl);

  // Search narrows within the filter. Words are matched separately (like Django's admin).
  await page.getByRole("searchbox", { name: "Search Posts" }).fill("number 039");
  await expect(page).toHaveURL(/q=number\+039/);
  await expect(page.getByText("1 row", { exact: true })).toBeVisible();
  await expect(table.getByRole("row").nth(1)).toContainText("Post number 039");

  // Related model through the sidebar.
  await page
    .getByRole("navigation", { name: "Models" })
    .getByRole("link", { name: "Authors" })
    .click();
  await expect(page.getByRole("heading", { name: "Authors" })).toBeVisible();
  await expect(page.getByText("5 rows", { exact: true })).toBeVisible();
  // EmailField, set by a site convention in tests/e2e/server.py, renders as a mailto link.
  await expect(page.getByRole("link", { name: "author0@example.com" })).toHaveAttribute(
    "href",
    "mailto:author0@example.com",
  );

  // Sign out: the session is gone server-side too.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("m/posts");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  expect(errors).toEqual([]);
});

test("reloading a deep link keeps the view", async ({ page }) => {
  await page.goto("login");
  await signIn(page);
  await page.goto("m/posts?sort=-title&f.published__eq=true");
  await expect(page.getByRole("columnheader", { name: /^Title/ })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  await expect(page.getByText("80 rows", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Published is Yes")).toBeVisible();
});

test("invalid view parameters get a way back", async ({ page }) => {
  await page.goto("login");
  await signIn(page);
  await page.goto("m/posts?sort=nonexistent");
  await expect(page.getByText("This view can't be shown")).toBeVisible();
  await page.getByRole("link", { name: "Reset the view" }).click();
  await expect(page.getByRole("table", { name: "Posts" })).toBeVisible();
});

test.describe("narrow screens", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("navigation opens in a dialog", async ({ page }) => {
    await page.goto("login");
    await signIn(page);
    await page.getByRole("button", { name: "Open navigation" }).click();
    const dialog = page.getByRole("dialog", { name: "Navigation" });
    await dialog.getByRole("link", { name: "Authors" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("heading", { name: "Authors" })).toBeVisible();
    await expectAccessible(page);
    await page
      .getByRole("table", { name: "Authors" })
      .getByRole("row")
      .nth(1)
      .getByRole("link")
      .first()
      .click();
    await expect(page.getByRole("heading", { name: "Record fields" })).toBeVisible();
    await expectAccessible(page);
    await page.getByRole("link", { name: "Edit" }).click();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
    await expectAccessible(page);
  });
});
