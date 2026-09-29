import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  IS_CI,
  expect,
  seededTenantId,
  serviceUrl,
  signInThroughForm,
  test,
  type Persona,
} from "./fixtures";

/**
 * The consent step against the real identity and notification services (make web-stack, then
 * make web-seed). Each test signs in through the fake provider as a new user of the seeded
 * tenant (a fresh display name gives a fresh user id), so no earlier run's consents are on file.
 */
const tenantId = seededTenantId();

function versionOf(document: string): string {
  const markdown = readFileSync(resolve(__dirname, `../../../docs/legal/${document}.md`), "utf8");
  const match = /^Version:[ \t]*(\S+)/m.exec(markdown);
  if (match === null) throw new Error(`${document} has no Version line`);
  return match[1] as string;
}

function newUser(tenantKind: Persona["tenantKind"], roles: Persona["roles"]): Persona {
  const suffix = randomUUID().slice(0, 8);
  return {
    key: `onboarding-${suffix}`,
    tenantKind,
    roles,
    displayName: `Example onboarding user ${suffix}`,
    ...(tenantKind === "business" && tenantId !== null ? { tenantId } : {}),
  };
}

const REQUIRED = [
  "I accept the terms of service.",
  "I have read the privacy notice.",
  /^Use the business identifiers and the profile answers I give/,
];
const WHATSAPP_BOX =
  "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.";
const NUMBER = "+919800000001";

test.describe("onboarding: consent step", () => {
  test.skip(
    !IS_CI && tenantId === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("a new owner agrees, opts a number in to WhatsApp and moves on to the business step", async ({
    page,
    checkA11y,
  }) => {
    expect(tenantId, "make web-seed writes var/seed/last.json").not.toBeNull();
    await signInThroughForm(page, newUser("business", ["owner"]), "/onboarding");
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Onboarding steps" }).locator("[aria-current='step']"),
    ).toContainText("Consents");
    await expect(
      page.getByRole("status").filter({ hasText: "Draft - to be reviewed by a lawyer" }),
    ).toContainText(`Privacy notice ${versionOf("privacy-notice")}`);
    for (const name of REQUIRED) {
      await expect(page.getByRole("checkbox", { name })).not.toBeChecked();
    }
    await expect(
      page.getByRole("link", {
        name: `Terms of service, version ${versionOf("terms-of-service")}`,
      }),
    ).toHaveAttribute("href", "/legal/terms-of-service");
    await expect(page.getByLabel("WhatsApp number")).toHaveCount(0);
    await checkA11y();

    // Nothing ticked: each required box says so, and nothing is recorded.
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(page.getByText("Tick this box to continue.")).toHaveCount(3);
    await expect(page.locator("[data-slot='consent-errors']")).toBeFocused();
    await expect(page).toHaveURL(/\/onboarding$/);

    for (const name of REQUIRED) await page.getByRole("checkbox", { name }).check();
    await page.getByRole("checkbox", { name: WHATSAPP_BOX }).check();
    await page.getByLabel("WhatsApp number").fill("98000");
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(
      page.getByText("Enter the number with its country code, starting with +."),
    ).toBeVisible();
    // The refused submit kept what was ticked.
    await expect(page.getByRole("checkbox", { name: WHATSAPP_BOX })).toBeChecked();
    await checkA11y();

    await page.getByLabel("WhatsApp number").fill(NUMBER);
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(page).toHaveURL(/\/onboarding\/business$/);
    await expect(page.getByRole("heading", { level: 1, name: "Add a business" })).toBeVisible();

    // The records are on file: the step now shows them with their notice versions.
    await page.goto("/onboarding");
    const accepted = page.locator("[data-slot='consent-accepted']");
    await expect(accepted).toContainText("You have agreed to the current documents");
    await expect(accepted).toContainText(
      `Terms of service: terms-of-service@${versionOf("terms-of-service")}`,
    );
    await expect(accepted).toContainText(
      `Processing of the business profile: privacy-notice@${versionOf("privacy-notice")}`,
    );
    await expect(accepted).toContainText(
      `WhatsApp reminders: whatsapp-consent@${versionOf("whatsapp-consent")}`,
    );
    await expect(accepted).toContainText("IST");
    await expect(page.getByRole("link", { name: "Continue to your business" })).toHaveAttribute(
      "href",
      "/onboarding/business",
    );
    await checkA11y();

    // And the number is opted in on the notification service, keyed as WhatsApp reports it.
    const response = await fetch(
      `${serviceUrl("notification")}/v1/notification/preferences/whatsapp/${NUMBER.slice(1)}`,
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ opted_in: true, source: "web_onboarding" });
  });

  test("a CA admin agrees without a WhatsApp box", async ({ page, checkA11y }) => {
    await signInThroughForm(page, newUser("ca_firm", ["ca_admin"]), "/onboarding");
    await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: WHATSAPP_BOX })).toHaveCount(0);
    await expect(
      page.getByText("WhatsApp reminders are set for each client business, not for the firm."),
    ).toBeVisible();
    await checkA11y();
    for (const name of REQUIRED) await page.getByRole("checkbox", { name }).check();
    await page
      .getByRole("checkbox", { name: /Send me reminders for this business by email/ })
      .check();
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(page).toHaveURL(/\/onboarding\/business$/);
    await page.goto("/onboarding");
    await expect(page.locator("[data-slot='consent-accepted']")).toContainText(
      "Email reminders: privacy-notice@",
    );
  });

  test("a compliance lead is sent to the forbidden page", async ({ page }) => {
    await signInThroughForm(page, newUser("business", ["compliance_lead"]), "/onboarding");
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
