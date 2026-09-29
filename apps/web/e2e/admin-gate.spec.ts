import { ANALYST, OWNER, expect, test } from "./fixtures";

test.describe("admin gate", () => {
  test("an anonymous visitor is sent to sign-in with the tool to return to", async ({ page }) => {
    await page.goto("/admin/review");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fadmin%2Freview$/);
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fadmin$/);
  });

  test("a tenant role gets a 404 for every admin path", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of ["/admin", "/admin/review", "/admin/nowhere"]) {
      const response = await page.goto(path);
      expect(response?.status(), path).toBe(404);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });

  test("a regulatory role opens the tools and sees its own menu", async ({ page, signIn }) => {
    await signIn(ANALYST);
    const response = await page.goto("/admin");
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: "Internal tools" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Account" })).toContainText(
      "Example analyst",
    );
    const sidebar = page.locator("aside");
    await expect(sidebar.getByRole("link", { name: "Internal users" })).toHaveCount(0);
    const forbidden = await page.goto("/admin/team");
    expect(forbidden?.status()).toBe(404);
  });
});
