import { SERVICE_NAMES } from "../src/shared/config/services.ts";
import { ANALYST, IS_CI, OWNER, expect, seededTenantId, serviceUrl, test } from "./fixtures";

/**
 * The system page against the stack: every service's health and readiness as the web server
 * probes them, compared with each service's own /health, the registry's view per service and the
 * web server's facts. It only reads, so it runs in parallel and again on the same stack.
 */
const PAGE = "/admin/system";

test.describe("system", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
  });

  test("an analyst sees every service up and ready, its version, and the web server's facts", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );
    await signIn(ANALYST);
    await page.goto("/admin");
    await page.locator("aside").getByRole("link", { name: "System", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
    await expect(page.getByRole("heading", { level: 1, name: "System" })).toBeVisible();
    const summary = page.locator("[data-slot='system-summary']");
    const stat = (label: string) =>
      summary
        .locator("[data-slot='stat-card']")
        .filter({ has: page.getByText(label, { exact: true }) })
        .locator("dd");
    const all = `${SERVICE_NAMES.length} of ${SERVICE_NAMES.length}`;
    await expect(stat("Answer their health check")).toHaveText(all);
    await expect(stat("Ready to serve")).toHaveText(all);
    await expect(page.locator("tr[data-service]")).toHaveCount(SERVICE_NAMES.length);
    for (const service of SERVICE_NAMES) {
      const response = await fetch(`${serviceUrl(service)}/health`);
      const health = (await response.json()) as { version: string };
      const row = page.locator(`tr[data-service='${service}']`);
      await expect(row).toContainText("Up");
      await expect(row).toContainText(`Version ${health.version}`);
      await expect(row).toContainText(serviceUrl(service));
    }
    await expect(page.locator("tr[data-registry='rulebook']")).toContainText(/Screens: \d+/);
    const facts = page.locator("[data-slot='web-facts']");
    await expect(facts).toContainText("test");
    await expect(facts).toContainText("Off (web.otel_enabled)");
    await checkA11y();

    await page.getByRole("button", { name: "Refresh" }).click();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();
    await expect(page.locator("tr[data-service]")).toHaveCount(SERVICE_NAMES.length);
  });
});
