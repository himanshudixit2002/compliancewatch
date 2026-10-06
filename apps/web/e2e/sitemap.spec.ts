import { ANALYST, expect, test } from "./fixtures";

test.describe("sitemap", () => {
  test("lists every section with routes, roles, status and awaited routes", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/sitemap");
    await expect(page.getByRole("heading", { level: 1, name: "All screens" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(5);
    const stats = page.locator("[data-screen='admin.review.stats']");
    await expect(stats).toContainText("GET /v1/rulebook/review/stats");
    await expect(stats).toContainText("services track (WP21)");
    await expect(stats).toContainText("Ready to build");
    await expect(page.locator("[data-screen='admin.error-reports']")).toContainText(
      "Waiting for a backend",
    );
    await expect(page.locator("[data-screen='system.sitemap']")).toContainText("Available");
    await expect(page.locator("[data-screen='admin.system']")).toContainText("Ready to build");
    await expect(page.locator("[data-screen='admin.flags']")).toContainText("Available");
    await checkA11y();
  });

  test("links a tool not built yet to its not-available notice", async ({ page, signIn }) => {
    await signIn(ANALYST);
    await page.goto("/sitemap");
    await page.getByRole("link", { name: "Review queue" }).click();
    await expect(page).toHaveURL(/\/admin\/review$/);
    await expect(page.getByRole("heading", { level: 1, name: "Review queue" })).toBeVisible();
    await expect(page.getByText("Not available yet")).toBeVisible();
  });
});
