import { inviteThroughDialog, signInByPhone, uniquePhone } from "./auth-helpers";
import { newTenantPersona } from "./business-helpers";
import { expect, signInThroughForm, test } from "./fixtures";

/**
 * Revocation reaches the browser: the proxy re-reads /me (every two seconds in this run,
 * playwright.config.ts) and signs out a session identity revoked. A colleague the owner
 * disables ends on the sign-in page saying so on their next navigation; a colleague whose
 * roles changed is signed out too and comes back with the new roles.
 */
test.describe("revocation", () => {
  test("a disabled colleague's next navigation ends on the sign-in page saying so", async ({
    browser,
    baseURL,
    page,
  }) => {
    const phone = uniquePhone();
    await signInThroughForm(page, newTenantPersona(), "/settings/team");
    await inviteThroughDialog(page, {
      contact: phone,
      name: "Example colleague",
      roles: ["Staff"],
    });
    const colleagueContext = await browser.newContext({ baseURL });
    try {
      const colleague = await colleagueContext.newPage();
      await signInByPhone(colleague, phone, "/account");
      await expect(colleague).toHaveURL(/\/account$/);
      await expect(colleague.getByRole("navigation", { name: "Account" })).toContainText(
        "Example colleague",
      );
      const row = page.locator("tbody tr").filter({ hasText: "Example colleague" });
      await row.getByRole("button", { name: "Disable Example colleague" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel(/Reason/).fill("Left the company in April 2000");
      await dialog.getByRole("button", { name: "Disable" }).click();
      await expect(dialog).toBeHidden();
      await expect(row.locator("[data-slot='status-chip']")).toHaveText("Disabled");
      // Past the re-read interval, the colleague's next page is the sign-in page.
      await colleague.waitForTimeout(2_500);
      await colleague.goto("/businesses");
      await expect(colleague).toHaveURL(/\/sign-in\?reason=signed-out$/);
      await expect(colleague.getByText(/Your session ended/)).toBeVisible();
      const cookies = await colleagueContext.cookies(baseURL ?? "http://localhost:3000");
      expect(cookies.find((cookie) => cookie.name === "cw_session")).toBeUndefined();
      // Signing in again is refused: the account is disabled.
      await colleague.goto("/sign-in?method=phone");
      await colleague.getByLabel(/Mobile number/).fill(phone);
      await colleague.getByRole("button", { name: "Send code" }).click();
      await colleague.getByLabel(/^Code/).fill("123456");
      await colleague.getByRole("button", { name: "Verify" }).click();
      await expect(colleague.getByText(/This account was disabled/)).toBeVisible();
    } finally {
      await colleagueContext.close();
    }
  });

  test("a colleague whose roles changed is signed out and comes back with the new roles", async ({
    browser,
    baseURL,
    page,
  }) => {
    const phone = uniquePhone();
    await signInThroughForm(page, newTenantPersona(), "/settings/team");
    await inviteThroughDialog(page, { contact: phone, name: "Example promoted", roles: ["Staff"] });
    const colleagueContext = await browser.newContext({ baseURL });
    try {
      const colleague = await colleagueContext.newPage();
      await signInByPhone(colleague, phone, "/account");
      await expect(colleague.locator("dl[data-slot='key-value']")).toContainText("Staff");
      const row = page.locator("tbody tr").filter({ hasText: "Example promoted" });
      await row.getByRole("button", { name: "Change the roles of Example promoted" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("checkbox", { name: "Compliance lead" }).check();
      await dialog.getByRole("button", { name: "Save roles" }).click();
      await expect(dialog).toBeHidden();
      await expect(row).toContainText("Compliance lead");
      await colleague.waitForTimeout(2_500);
      await colleague.goto("/account");
      await expect(colleague).toHaveURL(/\/sign-in\?reason=signed-out$/);
      await signInByPhone(colleague, phone, "/account");
      await expect(colleague.locator("dl[data-slot='key-value']")).toContainText("Compliance lead");
    } finally {
      await colleagueContext.close();
    }
  });
});
