import { CA_ADMIN, expect, test } from "./fixtures";

test.describe("account", () => {
  test.beforeEach(async ({ signIn }) => {
    await signIn(CA_ADMIN);
  });

  test("shows the session facts, the copy controls and the sign-out form", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/account");
    await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
    const facts = page.locator("dl[data-slot='key-value']");
    await expect(facts).toContainText("Example CA admin");
    await expect(facts).toContainText(CA_ADMIN.tenantId as string);
    await expect(facts).toContainText("CA firm");
    await expect(facts).toContainText("CA admin");
    await expect(facts).toContainText("Asserted by the development sign-in, not verified");
    await expect(facts).toContainText("IST");
    await expect(facts).toContainText("Development (fake)");
    await expect(page.getByRole("button", { name: "Copy Tenant id" })).toBeVisible();
    await expect(page.locator("[data-slot='banner']")).toContainText("/me");
    await expect(page.locator("main form[data-slot='sign-out']")).toHaveAttribute(
      "action",
      "/sign-out",
    );
    await checkA11y();
  });

  test("the header links the name to the account page", async ({ page }) => {
    await page.goto("/businesses");
    await page.getByRole("link", { name: "Example CA admin" }).click();
    await expect(page).toHaveURL(/\/account$/);
  });
});
