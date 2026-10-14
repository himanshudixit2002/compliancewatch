import { ANY_CODE, inviteThroughDialog, signInByPhone, uniquePhone } from "./auth-helpers";
import { newTenantPersona } from "./business-helpers";
import { OWNER, expect, signInThroughForm, test } from "./fixtures";

/**
 * Two-step verification on the fake adapter, where one confirm asserts the factor: a CA firm's
 * first admin meets it before the account exists; an invited CA admin signing in by phone meets
 * it before the session exists and comes back to where they were going; a signed-in owner
 * confirms it voluntarily and the account page shows it.
 */
test.describe("two-step verification", () => {
  test("a CA firm's new admin confirms the factor before the account exists", async ({
    page,
    checkA11y,
  }) => {
    const phone = uniquePhone();
    await page.goto("/sign-in?method=phone");
    await page.getByLabel(/Mobile number/).fill(phone);
    await page.getByRole("button", { name: "Send code" }).click();
    await page.getByLabel(/^Code/).fill(ANY_CODE);
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page).toHaveURL(/\/sign-up$/);
    await expect(
      page.getByText(/signs in with a second factor, which is set up next/),
    ).toBeVisible();
    await page.getByRole("radio", { name: /CA firm/ }).click();
    await page.getByLabel(/Name of the business or firm/).fill("Example New CA Associates");
    await page.getByLabel(/^Your name/).fill("Example new CA admin");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/account\/mfa$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Two-step verification" }),
    ).toBeVisible();
    await expect(page.getByText(/A second factor is required for these roles/)).toBeVisible();
    await expect(page.getByText("Development sign-in: nothing is verified")).toBeVisible();
    await checkA11y();
    await page.getByRole("button", { name: "Confirm second factor" }).click();
    await expect(page).toHaveURL(/\/onboarding$/);
    await page.goto("/account");
    const facts = page.locator("dl[data-slot='key-value']");
    await expect(facts).toContainText("Example New CA Associates");
    await expect(facts).toContainText("CA admin");
    await expect(facts).toContainText("Asserted by the development sign-in, not verified");
  });

  test("an invited CA admin signing in by phone meets the factor, then lands where they were going", async ({
    page,
  }) => {
    // The firm's admin (a persona, factor asserted) invites a second CA admin on the team page.
    const phone = uniquePhone();
    await signInThroughForm(page, newTenantPersona("ca_firm", ["ca_admin"]), "/settings/team");
    await expect(page).toHaveURL(/\/settings\/team$/);
    await inviteThroughDialog(page, {
      contact: phone,
      name: "Example second admin",
      roles: ["CA admin"],
    });
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await page.request.post("/sign-out");
    // The invited admin: phone, code, then the factor, then the page they asked for.
    await signInByPhone(page, phone, "/settings/team");
    await expect(page).toHaveURL(/\/account\/mfa\?next=%2Fsettings%2Fteam$/);
    await page.getByRole("button", { name: "Confirm second factor" }).click();
    await expect(page).toHaveURL(/\/settings\/team$/);
    await expect(page.getByRole("navigation", { name: "Account" })).toContainText(
      "Example second admin",
    );
    await expect(page.locator("tbody tr").filter({ hasText: "(you)" })).toContainText(
      "Example second admin",
    );
  });

  test("a signed-in owner confirms the factor voluntarily and the account page shows it", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(OWNER);
    await page.goto("/account");
    await expect(page.locator("dl[data-slot='key-value']")).toContainText("Not verified");
    await page
      .locator("[data-slot='account']")
      .getByRole("link", { name: "Two-step verification" })
      .click();
    await expect(page).toHaveURL(/\/account\/mfa$/);
    await expect(page.getByText(/Your roles do not require one/)).toBeVisible();
    await checkA11y();
    await page.getByRole("button", { name: "Confirm second factor" }).click();
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.locator("dl[data-slot='key-value']")).toContainText(
      "Asserted by the development sign-in, not verified",
    );
    await page.goto("/account/mfa");
    await expect(page.getByText("This session was signed in with a second factor.")).toBeVisible();
  });

  test("nobody at all is told to sign in first", async ({ page, checkA11y }) => {
    await page.goto("/account/mfa");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Faccount%2Fmfa$/);
    await checkA11y();
  });
});
