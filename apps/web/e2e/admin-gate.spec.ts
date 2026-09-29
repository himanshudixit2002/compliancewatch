import { ADMIN, ANALYST, COMPLIANCE_LEAD, OWNER, REVIEWER, expect, test } from "./fixtures";

test.describe("admin gate", () => {
  test("an anonymous visitor is sent to sign-in with the tool to return to", async ({ page }) => {
    await page.goto("/admin/review");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fadmin%2Freview$/);
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fadmin$/);
  });

  for (const persona of [OWNER, COMPLIANCE_LEAD]) {
    test(`a tenant role (${persona.key}) gets a 404 for every admin path, with no admin markup`, async ({
      page,
      signIn,
    }) => {
      await signIn(persona);
      for (const path of ["/admin", "/admin/review", "/admin/nowhere"]) {
        const response = await page.goto(path);
        expect(response?.status(), path).toBe(404);
        await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
        await expect(page.getByRole("navigation", { name: "Internal tools" })).toHaveCount(0);
        await expect(page.getByText("Internal tools. Environment:")).toHaveCount(0);
      }
    });
  }

  for (const persona of [REVIEWER, ADMIN]) {
    test(`the ${persona.key} role opens the internal tools`, async ({ page, signIn }) => {
      await signIn(persona);
      const response = await page.goto("/admin");
      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1, name: "Internal tools" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Account" })).toContainText(
        persona.displayName,
      );
    });
  }

  test("an unknown admin path is a 404 inside the admin shell, with a way back", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    const response = await page.goto("/admin/nowhere");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(page.getByText("Internal tools. Environment:")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to the internal tools" })).toHaveAttribute(
      "href",
      "/admin",
    );
    await checkA11y();
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
