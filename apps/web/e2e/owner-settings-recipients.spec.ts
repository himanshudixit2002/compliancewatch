import { randomInt } from "node:crypto";
import { createBusinessOnService, examplePan, newTenantPersona } from "./business-helpers";
import { IS_CI, expect, seededTenantId, serviceUrl, signInThroughForm, test } from "./fixtures";

/**
 * The notification recipients page against the real profile and notification services, each
 * test in a tenant of its own with businesses made on the profile service: adding a recipient,
 * reading it back from the service, changing it, a refused address and removing it.
 */
const PAGE = "/settings/notifications/recipients";

interface RecipientBody {
  id: string;
  role: string;
  language: string;
  digest_mode: string;
  org_label: string;
  addresses: { channel: string; address: string; position: number }[];
  businesses: { business_id: string; label: string }[];
}

/** GET /v1/notification/recipients?business_id= as the tenant. */
async function recipientsOnService(tenantId: string, businessId: string): Promise<RecipientBody[]> {
  const response = await fetch(
    `${serviceUrl("notification")}/v1/notification/recipients?business_id=${businessId}`,
    { headers: { "x-tenant-id": tenantId } },
  );
  expect(response.status).toBe(200);
  return ((await response.json()) as { items: RecipientBody[] }).items;
}

/** A synthetic number no other run uses: +91 and ten digits starting 00000. */
function exampleNumber(): string {
  return `+9100000${String(randomInt(0, 100_000)).padStart(5, "0")}`;
}

test.describe("notification recipients", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an owner adds a recipient, changes it, is refused a malformed number, and removes it", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const tenantId = persona.tenantId as string;
    const first = await createBusinessOnService(tenantId, {
      name: "Example Recipients Ltd",
      pan: examplePan(1),
    });
    const second = await createBusinessOnService(tenantId, {
      name: "Example Second Ltd",
      pan: examplePan(2),
    });
    const number = exampleNumber();
    const email = `desk-${number.slice(-5)}@example.com`;

    await signInThroughForm(page, persona, "/settings");
    await page.getByRole("link", { name: "Notification recipients" }).first().click();
    await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
    await expect(
      page.getByRole("heading", { level: 1, name: "Notification recipients" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "No recipients yet" })).toBeVisible();
    const picker = page.getByRole("form", { name: "Choose a business" });
    await expect(picker.getByLabel("Business")).toHaveValue(first.id);
    await checkA11y();

    const add = page.getByRole("form", { name: "Add a recipient" });
    await add.getByLabel(/^Role/).selectOption("staff");
    await add.getByLabel(/^Organisation/).fill("Example desk");
    await add.getByLabel("Address 1").fill(`${number.slice(0, 3)} ${number.slice(3)}`);
    await add.getByLabel("Channel of address 2").selectOption("email");
    await add.getByLabel("Address 2").fill(email.toUpperCase());
    await add.getByLabel(/^Delivery/).selectOption("daily");
    await add.getByRole("checkbox", { name: "Example Second Ltd" }).check();
    await add.getByRole("button", { name: "Add the recipient" }).click();

    await expect(page).toHaveURL(new RegExp(`\\?business=${first.id}&saved=`));
    await expect(page.getByText("Saved: Example desk.")).toBeVisible();
    const row = page.locator("tr[data-recipient]");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Example desk");
    await expect(row.locator("ol li")).toHaveText([`WhatsApp${number}`, `Email${email}`]);
    await expect(row).toContainText("Example Recipients Ltd, Example Second Ltd");
    await expect(row).toContainText("Daily digest");
    await checkA11y();

    const [saved] = await recipientsOnService(tenantId, first.id);
    expect(saved).toMatchObject({
      role: "staff",
      language: "en",
      digest_mode: "daily",
      org_label: "Example desk",
    });
    expect(saved?.addresses.map(({ channel, address }) => ({ channel, address }))).toEqual([
      { channel: "whatsapp", address: number },
      { channel: "email", address: email },
    ]);
    expect(saved?.businesses).toEqual(
      expect.arrayContaining([
        { business_id: first.id, label: "Example Recipients Ltd" },
        { business_id: second.id, label: "Example Second Ltd" },
      ]),
    );
    expect(await recipientsOnService(tenantId, second.id)).toHaveLength(1);

    await row.getByRole("link", { name: "Change Example desk" }).click();
    const change = page.getByRole("form", { name: "Change Example desk" });
    await expect(change.getByLabel("Address 1")).toHaveValue(number);
    await expect(change.getByLabel("Address 2")).toHaveValue(email);
    await change.getByLabel(/^Language/).selectOption("hi");
    await change.getByRole("button", { name: "Save the recipient" }).click();
    await expect(page.getByText("Saved: Example desk.")).toBeVisible();
    await expect(page.locator("tr[data-recipient]")).toContainText("Hindi");
    const [changed] = await recipientsOnService(tenantId, first.id);
    expect(changed?.id).toBe(saved?.id);
    expect(changed?.language).toBe("hi");

    const again = page.getByRole("form", { name: "Add a recipient" });
    await again.getByLabel("Address 1").fill("12345");
    await again.getByRole("button", { name: "Add the recipient" }).click();
    await expect(again.getByText("The recipient was not saved")).toBeVisible();
    await expect(
      again.getByText("Enter a WhatsApp number with its country code, starting with +."),
    ).toBeVisible();
    await expect(again.getByLabel("Address 1")).toHaveValue("12345");
    await expect(again.locator("[data-slot='recipient-form-summary']")).toBeFocused();
    await checkA11y();

    await page
      .locator("tr[data-recipient]")
      .getByRole("button", { name: "Remove Example desk" })
      .click();
    const dialog = page.getByRole("dialog", { name: "Remove Example desk?" });
    await expect(dialog).toContainText("Each address keeps its opt-in or opt-out.");
    await dialog.getByRole("button", { name: "Remove the recipient" }).click();
    await expect(page.getByText("The recipient was removed.")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "No recipients yet" })).toBeVisible();
    expect(await recipientsOnService(tenantId, first.id)).toEqual([]);
  });

  test("a CA admin is offered the firm's roles for a client's recipients", async ({ page }) => {
    const persona = newTenantPersona("ca_firm", ["ca_admin"]);
    const client = await createBusinessOnService(persona.tenantId as string, {
      name: "Example Client Ltd",
      pan: examplePan(3),
    });
    await signInThroughForm(page, persona, PAGE);
    await expect(
      page.getByRole("heading", { level: 2, name: "Recipients of Example Client Ltd" }),
    ).toBeVisible();
    const role = page.getByRole("form", { name: "Add a recipient" }).getByLabel(/^Role/);
    await expect(role.locator("option")).toHaveText(["CA admin", "CA staff"]);
    expect(client.id).toBeTruthy();
  });

  test("a tenant without a business is asked to add one", async ({ page, checkA11y }) => {
    await signInThroughForm(page, newTenantPersona(), PAGE);
    await expect(page.getByRole("heading", { level: 2, name: "No business yet" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add a business" })).toHaveAttribute(
      "href",
      "/onboarding/business",
    );
    await checkA11y();
  });

  test("a staff member is sent to the forbidden page", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("business", ["staff"]), PAGE);
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
