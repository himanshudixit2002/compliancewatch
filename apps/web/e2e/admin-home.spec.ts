import { ANALYST, expect, test } from "./fixtures";

test.describe("admin home", () => {
  test.beforeEach(async ({ signIn }) => {
    await signIn(ANALYST);
  });

  test("lists the internal tools from the registry with their status and services", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/admin");
    await expect(page.getByRole("heading", { level: 1, name: "Internal tools" })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Environment: test" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(7);
    const sources = page.locator("[data-tool='admin.sources']");
    await expect(sources).toContainText("services/pipeline/README.md");
    await expect(sources).toContainText("Waiting for a backend");
    await expect(page.locator("[data-tool='admin.flags']")).toContainText("Ready to build");
    await expect(page.getByRole("navigation", { name: "Internal tools" }).first()).toBeVisible();
    await checkA11y();
  });

  test("the sidebar opens a tool and marks it current", async ({ page }) => {
    await page.goto("/admin");
    const sidebar = page.locator("aside");
    await sidebar.getByRole("link", { name: "Sources" }).click();
    await expect(page).toHaveURL(/\/admin\/sources$/);
    await expect(sidebar.locator("[aria-current='page']")).toHaveText("Sources");
  });
});
