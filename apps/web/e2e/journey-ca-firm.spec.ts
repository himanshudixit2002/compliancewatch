import { REQUIRED_CONSENTS, newTenantPersona } from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * A CA firm's way through the product against the real services, with axe on every screen: an
 * admin of a new firm finds the empty client list, agrees to the documents (no WhatsApp box for a
 * firm), adds two clients through onboarding (the demo GSTIN, which the static lookup knows, and
 * one it does not), finds the second by searching the list, reads the review task its GSTIN
 * opened, and checks the firm's consents and billing. The screens' own specs cover each state.
 */
const DEMO_GSTIN = "29ABCDE1234F1Z5";
/** A well-formed GSTIN with another PAN, which the static lookup does not know. */
const OTHER_GSTIN = "27AAAPE0001Z1Z5";

test.describe("journey: a CA firm from sign-in to its clients", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("onboards two clients, finds one by search and checks the firm's settings", async ({
    page,
    checkA11y,
  }) => {
    test.setTimeout(120_000);
    await signInThroughForm(page, newTenantPersona("ca_firm", ["ca_admin"]));
    await expect(page).toHaveURL(/\/businesses$/);
    await expect(page.getByRole("heading", { level: 1, name: "Clients" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No client yet" })).toBeVisible();
    await checkA11y();
    await page.getByRole("link", { name: "Get started" }).click();

    // A firm agrees without a WhatsApp box; reminders are set per client.
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(
      page.getByText("WhatsApp reminders are set for each client business, not for the firm."),
    ).toBeVisible();
    await expect(page.getByLabel("WhatsApp number")).toHaveCount(0);
    await checkA11y();
    for (const name of REQUIRED_CONSENTS) await page.getByRole("checkbox", { name }).check();
    await page
      .getByRole("checkbox", { name: /Send me reminders for this business by email/ })
      .check();
    await page.getByRole("button", { name: "Agree and continue" }).click();

    // The first client, from the demo GSTIN.
    await expect(page).toHaveURL(/\/onboarding\/business$/);
    await page.getByRole("textbox", { name: /GSTIN/ }).fill(DEMO_GSTIN);
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Client One");
    await page.getByRole("button", { name: "Add the business" }).click();
    await expect(
      page.getByRole("heading", { level: 2, name: "Example Client One is added" }),
    ).toBeVisible();
    await checkA11y();

    // The second, from a GSTIN the lookup does not know: nothing is filled in, a task is opened.
    await page.getByRole("link", { name: "Add another business" }).click();
    await page.getByRole("textbox", { name: /GSTIN/ }).fill(OTHER_GSTIN);
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Client Two");
    await page.getByRole("button", { name: "Add the business" }).click();
    await expect(page.locator("[data-slot='prefill-manual']")).toContainText(
      "No lookup details for this GSTIN",
    );
    await checkA11y();

    // Both are on the firm's list; a search finds the second.
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Businesses" })
      .click();
    await expect(page).toHaveURL(/\/businesses$/);
    const status = page.locator("[data-slot='directory-status']");
    await expect(status).toHaveText("Page 1: 2 clients.");
    const rows = page
      .getByRole("table", { name: "Client businesses of your firm" })
      .locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await checkA11y();
    await page.getByRole("textbox", { name: /Search/ }).fill("client two");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(status).toHaveText('Page 1: 1 matching "client two".');
    await page.getByRole("link", { name: "Example Client Two" }).click();

    // Its pages: the GSTIN the lookup did not know waits for an analyst.
    await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Example Client Two" })).toBeVisible();
    await checkA11y();
    await page
      .getByRole("navigation", { name: "Pages of this business" })
      .getByRole("link", { name: "Review tasks", exact: true })
      .click();
    await expect(page.getByRole("table", { name: "Review tasks on this business" })).toContainText(
      "GSTIN details not verified by a lookup provider",
    );
    await checkA11y();

    // The firm's settings: its consents without WhatsApp, and billing for the CA admin.
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Settings", exact: true })
      .click();
    await expect(page.locator("[data-screen='owner.settings.billing']")).toBeVisible();
    await page.getByRole("link", { name: "Consents", exact: true }).click();
    const states = page.locator("[data-slot='consent-states']");
    await expect(states.locator("tr[data-purpose='email_reminders']")).toContainText("Given");
    await expect(states.locator("tr[data-purpose='whatsapp_reminders']")).toHaveCount(0);
    await checkA11y();
    await page
      .getByRole("navigation", { name: "Settings pages" })
      .getByRole("link", { name: "Billing" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "Billing" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Start a subscription" })).toBeVisible();
    await checkA11y();
  });
});
