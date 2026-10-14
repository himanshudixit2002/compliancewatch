import { inviteThroughDialog, uniqueEmail, uniquePhone } from "./auth-helpers";
import { newTenantPersona } from "./business-helpers";
import { ADMIN, ANALYST, OWNER, dismissToasts, expect, signInThroughForm, test } from "./fixtures";

/**
 * The team pages on identity's user routes with the session's bearer: an owner invites,
 * changes roles and disables a colleague, cannot disable themselves and stays the last admin;
 * the internal admin manages the regulatory team on /admin/team; the pages are each role's.
 */
test.describe("team", () => {
  test("an owner invites, promotes and disables a colleague, and stays the last admin", async ({
    page,
    checkA11y,
  }) => {
    const owner = newTenantPersona();
    await signInThroughForm(page, owner, "/settings/team");
    await expect(page).toHaveURL(/\/settings\/team$/);
    await expect(page.getByRole("heading", { level: 1, name: "Team" })).toBeVisible();
    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("(you)");
    await expect(page.getByRole("button", { name: `Disable ${owner.displayName}` })).toHaveCount(0);
    await checkA11y();

    // Invite: a role the kind lacks is not offered; the member appears with their roles.
    await page.getByRole("button", { name: "Invite" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("checkbox", { name: "Analyst" })).toHaveCount(0);
    await checkA11y("[role='dialog']");
    await dialog.getByRole("button", { name: "Send invitation" }).click();
    await expect(dialog.getByText("Enter a mobile number or an email address.")).toBeVisible();
    await dialog.getByLabel(/Mobile number or email address/).fill(uniquePhone());
    await dialog.getByLabel(/^Name/).fill("Example colleague");
    await dialog.getByRole("checkbox", { name: "Staff" }).check();
    await dialog.getByRole("button", { name: "Send invitation" }).click();
    await expect(dialog).toBeHidden();
    await expect(rows).toHaveCount(2);
    const colleague = rows.filter({ hasText: "Example colleague" });
    await expect(colleague).toContainText("Staff");
    await expect(colleague.locator("[data-slot='status-chip']")).toHaveText("Active");

    // Change roles: the current roles are ticked; the new ones show.
    await colleague.getByRole("button", { name: "Change the roles of Example colleague" }).click();
    await expect(dialog.getByRole("checkbox", { name: "Staff" })).toBeChecked();
    await dialog.getByRole("checkbox", { name: "Compliance lead" }).check();
    await dialog.getByRole("button", { name: "Save roles" }).click();
    await expect(dialog).toBeHidden();
    await expect(colleague).toContainText("Compliance lead");

    // The last admin keeps the admin role: identity's 409 shows in the dialog.
    await rows
      .filter({ hasText: "(you)" })
      .getByRole("button", { name: `Change the roles of ${owner.displayName}` })
      .click();
    await expect(dialog).toContainText("only admin");
    await dialog.getByRole("checkbox", { name: "Owner" }).uncheck();
    await dialog.getByRole("checkbox", { name: "Staff" }).check();
    await dialog.getByRole("button", { name: "Save roles" }).click();
    await expect(dialog.getByText(/Make someone else an admin first/)).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();

    // Disable, with a reason; the row keeps its status and loses its controls.
    await colleague.getByRole("button", { name: "Disable Example colleague" }).click();
    await expect(dialog.getByRole("button", { name: "Disable" })).toBeDisabled();
    await dialog.getByLabel(/Reason/).fill("Left the company in April 2000");
    await expect(dialog.getByRole("button", { name: "Disable" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Disable" }).click();
    await expect(dialog).toBeHidden();
    await expect(colleague.locator("[data-slot='status-chip']")).toHaveText("Disabled");
    await expect(colleague.getByRole("button")).toHaveCount(0);
    await expect(page.locator("[data-slot='stat-card']").nth(2)).toContainText("1");
    // The three toasts of the changes above are dismissed first: axe reads the page at rest.
    await dismissToasts(page);
    await checkA11y();
  });

  test("the internal admin manages the regulatory team, whose every role needs the factor", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ADMIN);
    await page.goto("/admin/team");
    await expect(page.getByRole("heading", { level: 1, name: "Internal users" })).toBeVisible();
    await expect(page.locator("[data-slot='team-mfa-note']")).toContainText("second factor");
    await checkA11y();
    const email = uniqueEmail("analyst");
    await page.getByRole("button", { name: "Invite" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("checkbox", { name: "Owner" })).toHaveCount(0);
    await expect(dialog.getByText("Signs in with a second factor.").first()).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await inviteThroughDialog(page, {
      contact: email,
      name: "Example new analyst",
      roles: ["Analyst"],
    });
    const row = page.locator("tbody tr").filter({ hasText: email });
    await expect(row).toContainText("Example new analyst");
    await expect(row).toContainText("Analyst");
  });

  test("the pages are each role's: an owner has no /admin/team, an analyst no /settings/team", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    expect((await page.goto("/admin/team"))?.status()).toBe(404);
    await page.request.post("/sign-out");
    await signIn(ANALYST);
    await page.goto("/settings/team");
    await expect(page).toHaveURL(/\/forbidden$/);
    expect((await page.goto("/admin/team"))?.status()).toBe(404);
  });

  test("a staff member cannot open the team page", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("business", ["staff"]), "/settings/team");
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
