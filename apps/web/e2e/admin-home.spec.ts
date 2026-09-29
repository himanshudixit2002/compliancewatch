import { expect, test } from "./fixtures";

// No session or allow-list exists yet: /admin renders for every visitor in local and test.
// The session package adds the sign-in redirect and the owner 404; the proxy adds the CIDR gate.
test.describe("admin home", () => {
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
