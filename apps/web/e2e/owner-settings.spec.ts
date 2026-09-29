import { newTenantPersona } from "./business-helpers";
import { expect, signInThroughForm, test } from "./fixtures";

/**
 * The settings index: reached from the header, it lists every settings and account page the
 * session may open, with its status, from the screen registry. It calls no service.
 */
test.describe("settings index", () => {
  test("an owner opens settings from the header and sees each page with its status", async ({
    page,
    checkA11y,
  }) => {
    await signInThroughForm(page, newTenantPersona());
    await page.goto("/businesses");
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    const pages = page.locator("#settings-pages").locator("..");
    await expect(pages.locator("[data-screen='owner.settings.consents']")).toContainText(
      "Available",
    );
    await expect(pages.locator("[data-screen='owner.settings.data-rights']")).toContainText(
      "Waiting for a backend",
    );
    await expect(pages.locator("[data-screen='owner.settings.billing']")).toBeVisible();
    await expect(page.locator("[data-screen='account.home']")).toBeVisible();
    await checkA11y();

    await page.getByRole("link", { name: "Consents", exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/consents$/);
    await expect(page.getByRole("heading", { level: 1, name: "Consents" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  test("a staff member sees no billing", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("business", ["staff"]), "/settings");
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    await expect(page.locator("[data-screen='owner.settings.billing']")).toHaveCount(0);
    await expect(page.locator("[data-screen='owner.settings.consents']")).toBeVisible();
  });

  test("an analyst is sent to the forbidden page", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("internal", ["analyst"]), "/settings");
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
