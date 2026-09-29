import { expect, test } from "./fixtures";

test.describe("home", () => {
  test("shows the landing with sign-in, sitemap and legal links", async ({ page, checkA11y }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "ComplianceWatch" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign in" }).first()).toHaveAttribute(
      "href",
      "/sign-in",
    );
    await expect(page.getByRole("link", { name: "Every screen and its status" })).toHaveAttribute(
      "href",
      "/sitemap",
    );
    await expect(page.getByRole("link", { name: "Privacy notice" })).toHaveAttribute(
      "href",
      "/legal/privacy-notice",
    );
    await checkA11y();
  });

  test("the skip link moves focus to the main landmark", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await skip.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();
  });

  test("the sign-in link leads to the sign-in form", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Sign in" }).first().click();
    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByLabel("Display name")).toBeVisible();
  });
});
