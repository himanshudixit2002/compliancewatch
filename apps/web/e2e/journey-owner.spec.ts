import { randomInt } from "node:crypto";
import type { Locator, Page } from "@playwright/test";
import { REQUIRED_CONSENTS, newTenantPersona, reviewTasksOnService } from "./business-helpers";
import {
  IS_CI,
  expect,
  seededTenantId,
  serviceUrl,
  signInThroughForm,
  test,
  waitForHydration,
} from "./fixtures";

/**
 * One owner's way through the product, screen after screen as a person takes it, against the
 * real services with axe on every screen: sign in to a new tenant and find the empty list, read
 * the privacy notice from the consent step, agree (with a WhatsApp number and analytics), add the
 * demo business, answer questions with each of the three answers, stop at the summary, walk the
 * business's pages, then the settings: withdraw analytics, set the quiet hours of the number
 * opted in at onboarding, try to subscribe, and sign out. The screens' own specs cover each
 * screen's states in depth; this one checks that they lead into each other.
 */
const DEMO_GSTIN = "29ABCDE1234F1Z5";
const NAME = "Example Journey Traders";
const BILLING = process.env.WEB_STACK_BILLING?.trim() || "none";
const WHATSAPP_BOX =
  "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.";
const ANALYTICS_BOX = "Record which screens I open and which steps I finish, to improve the app.";

async function heading(page: Page): Promise<string> {
  const text = (await page.getByRole("heading", { level: 1 }).textContent())?.trim() ?? "";
  expect(text.length).toBeGreaterThan(0);
  return text;
}

/** Answers the current question with a value: the first option, else a whole number. */
async function answerWithAValue(form: Locator): Promise<void> {
  if ((await form.getByRole("radio").count()) > 0) {
    await form.getByRole("radio").first().click();
  } else if ((await form.getByRole("checkbox").count()) > 0) {
    await form.getByRole("checkbox").first().check();
  } else {
    await form.getByRole("textbox").first().fill("12");
  }
  await form.getByRole("button", { name: "Save" }).click();
}

test.describe("journey: an owner from sign-in to settings", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("signs in, onboards the demo business, walks its pages and changes the settings", async ({
    page,
    checkA11y,
  }) => {
    test.setTimeout(120_000);
    const persona = newTenantPersona();
    const tenantId = persona.tenantId as string;
    const number = `+9197${String(randomInt(0, 100_000_000)).padStart(8, "0")}`;

    // Signed in, a new owner lands on the empty list, which points to onboarding.
    await signInThroughForm(page, persona);
    await expect(page).toHaveURL(/\/businesses$/);
    await expect(page.getByRole("heading", { name: "No business yet" })).toBeVisible();
    await checkA11y();
    await page.getByRole("link", { name: "Get started" }).click();

    // The consent step links each document; the privacy notice is a draft.
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
    await checkA11y();
    await page
      .getByRole("link", { name: /^Privacy notice, version \S+-draft$/ })
      .first()
      .click();
    await expect(page).toHaveURL(/\/legal\/privacy-notice$/);
    await expect(page.getByRole("heading", { level: 1, name: "Privacy notice" })).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Draft - to be reviewed by a lawyer" }),
    ).toBeVisible();
    await checkA11y();
    await page.goBack();
    await expect(page).toHaveURL(/\/onboarding$/);
    await waitForHydration(page, "main form");

    for (const name of REQUIRED_CONSENTS) await page.getByRole("checkbox", { name }).check();
    await page.getByRole("checkbox", { name: WHATSAPP_BOX }).check();
    await page.getByLabel("WhatsApp number").fill(number);
    await page.getByRole("checkbox", { name: ANALYTICS_BOX }).check();
    await page.getByRole("button", { name: "Agree and continue" }).click();

    // The business step adds the demo business; the static lookup fills it in.
    await expect(page).toHaveURL(/\/onboarding\/business$/);
    await expect(page.getByRole("heading", { level: 1, name: "Add a business" })).toBeVisible();
    await checkA11y();
    await page.getByRole("textbox", { name: /GSTIN/ }).fill(DEMO_GSTIN);
    await page.getByRole("textbox", { name: /Business name/ }).fill(NAME);
    await page.getByRole("button", { name: "Add the business" }).click();
    await expect(page.getByRole("heading", { level: 2, name: `${NAME} is added` })).toBeFocused();
    await expect(
      page.getByRole("heading", { level: 3, name: "What the GSTIN lookup returned" }),
    ).toBeVisible();
    await checkA11y();
    await page.getByRole("link", { name: "Continue to the questions" }).click();

    // Three questions, one of each answer, then the summary.
    await expect(page).toHaveURL(/\/onboarding\/[0-9a-f-]{36}\/questions$/);
    const businessId = new URL(page.url()).pathname.split("/")[2] as string;
    const form = page.locator("[data-slot='answer-form']");
    let current = await heading(page);
    await checkA11y();
    await form.getByRole("button", { name: "Not sure" }).click();
    await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(current);
    current = await heading(page);
    await answerWithAValue(form);
    await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(current);
    await expect(
      page.getByRole("status").filter({ hasText: "Saved your answer about" }),
    ).toBeVisible();
    await form.getByRole("button", { name: "Does not apply" }).click();
    await expect(page.getByText(/It opened a review task an analyst will look at/)).toBeVisible();
    await checkA11y();
    await page.getByRole("link", { name: "Stop here and see the summary" }).click();

    await expect(page).toHaveURL(new RegExp(`/onboarding/${businessId}/done$`));
    await expect(page.getByRole("heading", { level: 1, name: "Onboarding summary" })).toBeVisible();
    await expect(
      page
        .locator("section")
        .filter({ has: page.getByRole("heading", { name: "Answered Not sure" }) })
        .getByRole("listitem"),
    ).toHaveCount(1);
    await expect(
      page.getByRole("table", { name: "Open review tasks on this business" }),
    ).toContainText("You said this does not apply; an analyst will confirm");
    await checkA11y();
    await page.getByRole("link", { name: "Open the business" }).click();

    // The business's pages, tab after tab.
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}$`));
    await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
    await checkA11y();
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    for (const [tab, path] of [
      ["Profile", "profile"],
      ["Attributes", "attributes"],
      ["Snapshot", "snapshot"],
      ["Review tasks", "review-tasks"],
    ] as const) {
      await tabs.getByRole("link", { name: tab, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/b/${businessId}/${path}$`));
      await expect(page.getByRole("heading", { level: 1, name: tab })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(NAME);
      await checkA11y();
    }
    await expect(page.getByRole("table", { name: "Review tasks on this business" })).toContainText(
      "You said this does not apply; an analyst will confirm",
    );
    const business = await fetch(`${serviceUrl("profile")}/v1/businesses/${businessId}`, {
      headers: { "x-tenant-id": tenantId },
    });
    const nodes = [
      businessId,
      ...((await business.json()) as { registrations: { id: string }[] }).registrations.map(
        (node) => node.id,
      ),
    ];
    const reasons = (await Promise.all(nodes.map((id) => reviewTasksOnService(tenantId, id))))
      .flat()
      .filter((task) => task.open)
      .map((task) => task.reason);
    expect(reasons).toContain("not_applicable");

    // With one business, the list now opens it.
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Businesses" })
      .click();
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}$`));

    // Settings: the consents given at onboarding, and analytics withdrawn.
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Settings", exact: true })
      .click();
    await expect(page).toHaveURL(/\/settings$/);
    await checkA11y();
    await page.getByRole("link", { name: "Consents", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Consents" })).toBeVisible();
    const states = page.locator("[data-slot='consent-states']");
    await expect(states.locator("tr[data-purpose='analytics']")).toContainText("Given");
    await expect(states.locator("tr[data-purpose='whatsapp_reminders']")).toContainText("Given");
    await checkA11y();
    await page.getByRole("button", { name: "Withdraw: Product analytics" }).click();
    const dialog = page.getByRole("dialog", { name: "Withdraw Product analytics?" });
    await checkA11y("[role='dialog']");
    await dialog.getByRole("button", { name: "Withdraw", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(states.locator("tr[data-purpose='analytics']")).toContainText("Withdrawn");

    // Notifications: the number opted in at onboarding, with new quiet hours.
    const settingsTabs = page.getByRole("navigation", { name: "Settings pages" });
    await settingsTabs.getByRole("link", { name: "Notifications" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    const whatsapp = page.getByRole("region", { name: "WhatsApp" });
    await expect(whatsapp).toContainText(`WhatsApp number: ${number}`);
    await checkA11y();
    await whatsapp.getByLabel("From").fill("22:30");
    await whatsapp.getByLabel("Until").fill("06:30");
    await whatsapp.getByRole("button", { name: "Save the preference" }).click();
    await expect(whatsapp.locator("[data-slot='preference-status']")).toContainText(
      "22:30 to 06:30 IST, across midnight",
    );
    await checkA11y();

    // Billing: the plans, and a subscribe that answers in the state the stack is in.
    await settingsTabs.getByRole("link", { name: "Billing" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Billing" })).toBeVisible();
    const subscribe = page.getByRole("form", { name: "Start a subscription" });
    await subscribe.getByLabel("Billing email").fill("owner@example.com");
    await subscribe.getByLabel("Billing name").fill(NAME);
    await subscribe.getByRole("button", { name: "Start the subscription" }).click();
    const result = page.locator("[data-slot='subscribe-result']");
    await expect(
      BILLING === "memory"
        ? result.locator("[data-slot='subscription']")
        : result.locator("[data-slot='billing-disabled']"),
    ).toBeVisible();
    await checkA11y();

    // Signing out ends the session: the list asks for a sign-in again.
    await page
      .getByRole("navigation", { name: "Account" })
      .getByRole("button", { name: "Sign out" })
      .click();
    await expect(page).toHaveURL(/\/sign-in$/);
    await page.goto("/businesses");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fbusinesses$/);
  });
});
