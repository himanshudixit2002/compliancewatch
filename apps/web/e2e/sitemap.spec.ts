import { SCREENS } from "../src/shared/config/screens.ts";
import { ANALYST, expect, test } from "./fixtures";

// The registry says which screens still wait for a backend; the first of them stands in for the
// waiting row, so a package that delivers a backend does not break this test.
const WAITING = SCREENS.find((screen) => screen.status === "waiting" && screen.awaits.length > 0);

test.describe("sitemap", () => {
  test("lists every section with routes, roles, status and awaited routes", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/sitemap");
    await expect(page.getByRole("heading", { level: 1, name: "All screens" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(5);
    const reports = page.locator("[data-screen='admin.error-reports']");
    await expect(reports).toContainText("GET /v1/rulebook/error-reports");
    await expect(reports).toContainText("services track (WP24)");
    await expect(reports).toContainText("Ready to build");
    if (WAITING !== undefined) {
      const row = page.locator(`[data-screen='${WAITING.id}']`);
      await expect(row).toContainText("Waiting for a backend");
      const awaited = WAITING.awaits[0];
      if (awaited !== undefined) {
        await expect(row).toContainText(`${awaited.method} ${awaited.path}`);
      }
    }
    await expect(page.locator("[data-screen='admin.review.stats']")).toContainText("Available");
    await expect(page.locator("[data-screen='system.sitemap']")).toContainText("Available");
    await expect(page.locator("[data-screen='admin.system']")).toContainText("Available");
    await expect(page.locator("[data-screen='admin.evals.run']")).toContainText("Ready to build");
    await expect(page.locator("[data-screen='admin.flags']")).toContainText("Available");
    await checkA11y();
  });

  test("links a tool not built yet to its not-available notice", async ({ page, signIn }) => {
    await signIn(ANALYST);
    await page.goto("/sitemap");
    await page.getByRole("link", { name: "Error reports" }).click();
    await expect(page).toHaveURL(/\/admin\/error-reports$/);
    await expect(page.getByRole("heading", { level: 1, name: "Error reports" })).toBeVisible();
    await expect(page.getByText("Not available yet")).toBeVisible();
  });
});
