import { randomInt, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { REQUIRED_CONSENTS } from "./business-helpers";
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
 * The consents settings page against the real identity and notification services (make
 * web-stack, then make web-seed). Each test signs in as a new user of the seeded tenant, so no
 * earlier run's records are on file, and uses a WhatsApp number of its own, since preferences
 * are kept per number across tenants.
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
    key: `consents-${suffix}`,
    tenantKind,
    roles,
    displayName: `Example consents user ${suffix}`,
    ...(tenantKind === "business" && tenantId !== null ? { tenantId } : {}),
  };
}

/** A number of this test's own: +9199 and eight random digits. */
function exampleNumber(): string {
  return `+9199${String(randomInt(0, 100_000_000)).padStart(8, "0")}`;
}

const WHATSAPP_BOX =
  "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.";

async function preferenceOf(number: string): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${serviceUrl("notification")}/v1/notification/preferences/whatsapp/${number.slice(1)}`,
  );
  expect(response.status).toBe(200);
  return (await response.json()) as Record<string, unknown>;
}

test.describe("settings: consents", () => {
  test.skip(
    !IS_CI && tenantId === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an owner withdraws WhatsApp reminders, which opts the number out, and gives analytics", async ({
    page,
    checkA11y,
  }) => {
    const number = exampleNumber();
    await signInThroughForm(page, newUser("business", ["owner"]), "/onboarding");
    for (const name of REQUIRED_CONSENTS) await page.getByRole("checkbox", { name }).check();
    await page.getByRole("checkbox", { name: WHATSAPP_BOX }).check();
    await page.getByLabel("WhatsApp number").fill(number);
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(page).toHaveURL(/\/onboarding\/business$/);
    expect(await preferenceOf(number)).toMatchObject({ opted_in: true });

    await page.goto("/settings/consents");
    await expect(page.getByRole("heading", { level: 1, name: "Consents" })).toBeVisible();
    const states = page.locator("[data-slot='consent-states']");
    const whatsapp = states.locator("tr[data-purpose='whatsapp_reminders']");
    await expect(whatsapp).toContainText("Given");
    await expect(whatsapp).toContainText(`whatsapp-consent@${versionOf("whatsapp-consent")}`);
    await expect(states.locator("tr[data-purpose='terms']")).toContainText(
      "Required to use the service",
    );
    const history = page.locator("[data-slot='consent-history'] tbody tr");
    await expect(history).toHaveCount(4);
    await checkA11y();

    // The number the consent step opted in is remembered on this device.
    await page.getByRole("button", { name: "Withdraw: WhatsApp reminders" }).click();
    const dialog = page.getByRole("dialog", { name: "Withdraw WhatsApp reminders?" });
    await expect(dialog).toContainText("granted false");
    await expect(dialog.getByLabel("WhatsApp number")).toHaveValue(number);
    await checkA11y("[role='dialog']");
    await dialog.getByRole("button", { name: "Withdraw", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(
      page.locator(
        "[data-slot='consent-change'][data-purpose='whatsapp_reminders'] [role='status']",
      ),
    ).toContainText(`Withdrawn: WhatsApp reminders, recorded`);
    await expect(whatsapp).toContainText("Withdrawn");
    await expect(history).toHaveCount(5);
    await expect(history.last()).toContainText(
      "Confirmed on the settings page: Withdraw consent: WhatsApp reminders.",
    );
    await expect(history.last()).toContainText(`whatsapp-consent@${versionOf("whatsapp-consent")}`);
    expect(await preferenceOf(number)).toMatchObject({
      opted_in: false,
      source: "web_onboarding",
    });

    await page.getByRole("button", { name: "Give consent: Product analytics" }).click();
    const give = page.getByRole("dialog", { name: "Give consent to Product analytics?" });
    await expect(give).toContainText(
      "Record which screens I open and which steps I finish, to improve the app.",
    );
    await give.getByRole("button", { name: "Agree" }).click();
    await expect(give).toHaveCount(0);
    await expect(states.locator("tr[data-purpose='analytics']")).toContainText("Given");
    await expect(history).toHaveCount(6);
    await checkA11y();
  });

  test("giving WhatsApp reminders asks for the number and opts it in", async ({ page }) => {
    const number = exampleNumber();
    await signInThroughForm(page, newUser("business", ["staff"]), "/settings/consents");
    await expect(
      page.getByRole("heading", { name: "No consent recorded for you yet" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Give consent: WhatsApp reminders" }).click();
    const dialog = page.getByRole("dialog", { name: "Give consent to WhatsApp reminders?" });
    await dialog.getByRole("button", { name: "Agree" }).click();
    await expect(dialog).toContainText("Enter the WhatsApp number the reminders go to.");
    await dialog.getByLabel("WhatsApp number").fill(number);
    await dialog.getByRole("button", { name: "Agree" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(
      page.locator(
        "[data-slot='consent-change'][data-purpose='whatsapp_reminders'] [role='status']",
      ),
    ).toContainText(`${number} is opted in.`);
    expect(await preferenceOf(number)).toMatchObject({ opted_in: true });
  });

  test("a CA admin has no WhatsApp row", async ({ page, checkA11y }) => {
    await signInThroughForm(page, newUser("ca_firm", ["ca_admin"]), "/settings/consents");
    await expect(page.getByRole("heading", { level: 1, name: "Consents" })).toBeVisible();
    await expect(page.locator("tr[data-purpose='whatsapp_reminders']")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Get started" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
    await checkA11y();
  });

  test("a compliance lead sees the page without a consent step to go to", async ({ page }) => {
    await signInThroughForm(page, newUser("business", ["compliance_lead"]), "/settings/consents");
    await expect(page.getByRole("heading", { level: 1, name: "Consents" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Get started" })).toHaveCount(0);
    await expect(page.getByText(/Reminders and analytics can be given above/)).toBeVisible();
  });
});
