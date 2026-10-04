import { randomUUID } from "node:crypto";
import {
  createBusinessOnService,
  examplePan,
  newTenantPersona,
  seededBusinessId,
} from "./business-helpers";
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
 * The reminders pages against the real notification and profile services. The seeded business
 * has one notification, the opt-in confirmation `make web-seed` sends; its state depends on the
 * stack (failed while WhatsApp is not wired, queued inside the quiet hours), so the spec reads
 * the record from the service and compares the page with it rather than assuming a state.
 */
interface NotificationBody {
  id: string;
  template_key: string;
  state: string;
  attempts: number;
  address: string;
  error: string;
}

const STATE_LABELS: Readonly<Record<string, string>> = {
  queued: "Queued",
  digest_pending: "Waiting for the digest",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Failed",
  suppressed: "Suppressed",
};

/** "opt_in_confirmed" as the page names it: "Opt in confirmed". */
function titleOf(templateKey: string): string {
  const words = templateKey.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function historyOnService(tenantId: string, businessId: string): Promise<NotificationBody[]> {
  const response = await fetch(
    `${serviceUrl("notification")}/v1/notification/notifications?business_id=${businessId}`,
    { headers: { "x-tenant-id": tenantId } },
  );
  expect(response.status).toBe(200);
  return ((await response.json()) as { items: NotificationBody[] }).items;
}

test.describe("reminders", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("the seeded owner reads the business's notifications, filters them and opens one", async ({
    page,
    checkA11y,
  }) => {
    const tenantId = seededTenantId() as string;
    const businessId = seededBusinessId() as string;
    const history = await historyOnService(tenantId, businessId);
    expect(history.length, "make web-seed sends the opt-in confirmation").toBeGreaterThan(0);
    const newest = history[0] as NotificationBody;
    const persona: Persona = {
      key: "seeded-reminders-owner",
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example reminders owner",
      tenantId,
    };

    await signInThroughForm(page, persona, `/b/${businessId}`);
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await tabs.getByRole("link", { name: "Reminders" }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}/reminders$`));
    await expect(page.getByRole("heading", { level: 1, name: "Reminders" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: "Reminders" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.locator("tr[data-notification]")).toHaveCount(Math.min(history.length, 25));
    const row = page.locator(`tr[data-notification='${newest.id}']`);
    await expect(row).toContainText(newest.template_key);
    await expect(row).toContainText(STATE_LABELS[newest.state] as string);
    await expect(row).toContainText(newest.address.slice(-4));
    await expect(row).not.toContainText(newest.address);
    await checkA11y();

    const filter = page.getByRole("form", { name: "Filter the notifications" });
    await filter.getByLabel("Delivery state").selectOption(newest.state);
    await filter.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(new RegExp(`\\?state=${newest.state}$`));
    await expect(page.locator(`tr[data-notification='${newest.id}']`)).toBeVisible();
    const absent = newest.state === "read" ? "delivered" : "read";
    await page
      .getByRole("form", { name: "Filter the notifications" })
      .getByLabel("Delivery state")
      .selectOption(absent);
    await page
      .getByRole("form", { name: "Filter the notifications" })
      .getByRole("button", { name: "Show" })
      .click();
    await expect(
      page.getByRole("heading", { level: 2, name: "No notification in this state" }),
    ).toBeVisible();
    await page.goto(`/b/${businessId}/reminders`);

    await page
      .locator(`tr[data-notification='${newest.id}']`)
      .getByRole("link", { name: titleOf(newest.template_key) })
      .click();
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}/reminders/${newest.id}$`));
    await expect(
      page.getByRole("heading", { level: 1, name: titleOf(newest.template_key) }),
    ).toBeVisible();
    const record = page.locator("dl[aria-label='Delivery record']");
    await expect(record).toContainText(STATE_LABELS[newest.state] as string);
    await expect(record).toContainText(newest.template_key);
    await expect(record).toContainText(newest.address.slice(-4));
    await expect(record).not.toContainText(newest.address);
    await expect(record).toContainText(newest.id);
    if (newest.error !== "") {
      await expect(page.locator("[data-slot='notification-error']")).toHaveText(newest.error);
    }
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Reminders");
    await checkA11y();
    await page.getByRole("link", { name: "All notifications of this business" }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}/reminders$`));
  });

  test("a business without notifications says so, and other tenants' or unknown ones are not found", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: "Example Quiet Ltd",
      pan: examplePan(1),
    });
    await signInThroughForm(page, persona, `/b/${business.id}/reminders`);
    await expect(page.getByRole("heading", { level: 1, name: "Reminders" })).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 2, name: "No notifications yet" }),
    ).toBeVisible();
    await checkA11y();

    const seeded = seededBusinessId() as string;
    for (const path of [
      `/b/${seeded}/reminders`,
      `/b/${business.id}/reminders/${randomUUID()}`,
      `/b/${business.id}/reminders/not-an-id`,
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });
});
