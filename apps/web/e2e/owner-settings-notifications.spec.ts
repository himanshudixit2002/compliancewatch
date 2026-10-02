import { randomInt, randomUUID } from "node:crypto";
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
 * The notifications page against the real identity and notification services (make web-stack,
 * then make web-seed). Each test signs in as a new user of the seeded tenant and uses a number
 * or address of its own, since preferences are kept per recipient across tenants.
 */
const tenantId = seededTenantId();

function newUser(roles: Persona["roles"] = ["owner"]): Persona {
  const suffix = randomUUID().slice(0, 8);
  return {
    key: `notifications-${suffix}`,
    tenantKind: "business",
    roles,
    displayName: `Example notifications user ${suffix}`,
    ...(tenantId !== null ? { tenantId } : {}),
  };
}

function exampleNumber(): string {
  return `+9198${String(randomInt(0, 100_000_000)).padStart(8, "0")}`;
}

async function preferenceOn(channel: string, recipient: string): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${serviceUrl("notification")}/v1/notification/preferences/${channel}/${encodeURIComponent(recipient)}`,
  );
  expect(response.status).toBe(200);
  return (await response.json()) as Record<string, unknown>;
}

const WHATSAPP_BOX =
  "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.";

test.describe("settings: notifications", () => {
  test.skip(
    !IS_CI && tenantId === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an owner changes the language and the quiet hours of the number opted in at onboarding", async ({
    page,
    checkA11y,
  }) => {
    const number = exampleNumber();
    await signInThroughForm(page, newUser(), "/onboarding");
    for (const name of REQUIRED_CONSENTS) await page.getByRole("checkbox", { name }).check();
    await page.getByRole("checkbox", { name: WHATSAPP_BOX }).check();
    await page.getByLabel("WhatsApp number").fill(number);
    await page.getByRole("button", { name: "Agree and continue" }).click();
    await expect(page).toHaveURL(/\/onboarding\/business$/);

    await page.goto("/settings/notifications");
    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    const whatsapp = page.getByRole("region", { name: "WhatsApp" });
    await expect(whatsapp).toContainText(`WhatsApp number: ${number}`);
    await expect(whatsapp).toContainText("Your consent to WhatsApp reminders is on file.");
    const recorded = whatsapp.locator("[data-slot='preference']");
    await expect(recorded).toContainText("Opted in");
    await expect(recorded).toContainText("21:00 to 08:00 IST, across midnight");
    await checkA11y();

    await whatsapp.getByLabel("Language").selectOption("hi");
    await whatsapp.getByLabel("From").fill("22:00");
    await whatsapp.getByLabel("Until").fill("07:00");
    await whatsapp.getByRole("button", { name: "Save the preference" }).click();
    await expect(whatsapp.locator("[data-slot='preference-status']")).toContainText(
      `Saved for ${number} at`,
    );
    await expect(whatsapp.locator("[data-slot='preference-status']")).toContainText(
      "22:00 to 07:00 IST, across midnight",
    );
    expect(await preferenceOn("whatsapp", number.slice(1))).toMatchObject({
      opted_in: true,
      language: "hi",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
      source: "web_settings",
    });

    await page.reload();
    await expect(recorded).toContainText("Hindi");
    await expect(recorded).toContainText("22:00 to 07:00 IST, across midnight");
    await expect(whatsapp.getByLabel("From")).toHaveValue("22:00");

    await whatsapp.getByRole("radio", { name: "Do not send reminders" }).click();
    await whatsapp.getByRole("button", { name: "Save the preference" }).click();
    await expect(whatsapp.locator("[data-slot='preference-status']")).toContainText("Opted out");
    expect(await preferenceOn("whatsapp", number.slice(1))).toMatchObject({ opted_in: false });
    await checkA11y();
  });

  test("an address without the email consent can be opted out but not in", async ({
    page,
    checkA11y,
  }) => {
    const address = `example-${randomUUID().slice(0, 8)}@example.com`;
    await signInThroughForm(page, newUser(["staff"]), "/settings/notifications");
    const email = page.getByRole("region", { name: "Email" });
    await expect(email).toContainText("does not deliver email yet");
    await email.getByLabel("Email address").fill("not-an-address");
    await email.getByRole("button", { name: "Show its preference" }).click();
    await expect(email).toContainText("Enter an email address, such as name@example.com.");
    await email.getByLabel("Email address").fill(address.toUpperCase());
    await email.getByRole("button", { name: "Show its preference" }).click();
    await expect(email).toContainText(`Email address: ${address}`);
    await expect(email).toContainText("Nothing is recorded for this recipient");
    await expect(email).toContainText("Email reminders: consent not on file");
    await checkA11y();

    await email.getByRole("radio", { name: "Send reminders", exact: true }).click();
    await email.getByRole("button", { name: "Save the preference" }).click();
    await expect(email).toContainText(
      "Your consent to Email reminders is not on file, so reminders were not switched on.",
    );

    await email.getByRole("radio", { name: "Do not send reminders" }).click();
    await email.getByRole("button", { name: "Save the preference" }).click();
    await expect(email.locator("[data-slot='preference-status']")).toContainText(
      `Saved for ${address} at`,
    );
    expect(await preferenceOn("email", address)).toMatchObject({
      opted_in: false,
      source: "web_settings",
    });

    await email.getByRole("button", { name: "Use another address" }).click();
    await expect(email.getByLabel("Email address")).toHaveValue("");
  });
});
