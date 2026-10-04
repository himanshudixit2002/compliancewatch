import { randomUUID } from "node:crypto";
import { seededBusinessId } from "./business-helpers";
import {
  ADMIN,
  ANALYST,
  IS_CI,
  OWNER,
  REVIEWER,
  expect,
  seededTenantId,
  serviceUrl,
  test,
} from "./fixtures";

/**
 * The notification console and the message templates against the real notification service.
 * The console reads one business of one tenant at a time (the routes are tenant-scoped), so it is
 * looked up with the seeded tenant and business, whose one notification is the opt-in
 * confirmation `make web-seed` sends; the page is compared with the service's record. Read-only,
 * so it runs in parallel and again on the same stack.
 */
interface NotificationBody {
  id: string;
  template_key: string;
  state: string;
  address: string;
  obligation_id: string;
}

interface TemplateBody {
  key: string;
  channel: string;
  language: string;
  body: string;
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

function titleOf(templateKey: string): string {
  const words = templateKey.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function newestOnService(tenantId: string, businessId: string): Promise<NotificationBody> {
  const response = await fetch(
    `${serviceUrl("notification")}/v1/notification/notifications?business_id=${businessId}`,
    { headers: { "x-tenant-id": tenantId } },
  );
  expect(response.status).toBe(200);
  const items = ((await response.json()) as { items: NotificationBody[] }).items;
  expect(items.length, "make web-seed sends the opt-in confirmation").toBeGreaterThan(0);
  return items[0] as NotificationBody;
}

test.describe("notification console", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an analyst looks up the seeded business, reads its history and opens a notification", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    const tenantId = seededTenantId() as string;
    const businessId = seededBusinessId() as string;
    const newest = await newestOnService(tenantId, businessId);
    await signIn(ANALYST);
    await page.goto("/admin");
    await page.locator("aside").getByRole("link", { name: "Notifications", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/notifications$/);
    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    await checkA11y();

    const lookup = page.getByRole("form", { name: "Look up a business's notifications" });
    await lookup.getByLabel(/^Tenant id/).fill("not-a-tenant");
    await lookup.getByLabel(/^Business id/).fill(businessId);
    await lookup.getByRole("button", { name: "Show the notifications" }).click();
    await expect(page.getByText("Enter the tenant's id, a UUID.")).toBeVisible();
    await expect(page.getByLabel(/^Business id/)).toHaveValue(businessId);

    await page.getByLabel(/^Tenant id/).fill(tenantId);
    await page.getByRole("button", { name: "Show the notifications" }).click();
    await expect(page).toHaveURL(new RegExp(`\\?tenant=${tenantId}&business=${businessId}$`));
    await expect(
      page.getByRole("heading", { level: 2, name: "Notifications of the business" }),
    ).toBeVisible();
    const row = page.locator(`tr[data-notification='${newest.id}']`);
    await expect(row).toContainText(newest.template_key);
    await expect(row).toContainText(STATE_LABELS[newest.state] as string);
    await expect(row).toContainText(newest.address.slice(-4));
    await expect(row).not.toContainText(newest.address);
    await checkA11y();

    await row.getByRole("link", { name: titleOf(newest.template_key) }).click();
    await expect(page).toHaveURL(
      new RegExp(`/admin/notifications/${newest.id}\\?tenant=${tenantId}&business=${businessId}$`),
    );
    await expect(
      page.getByRole("heading", { level: 1, name: titleOf(newest.template_key) }),
    ).toBeVisible();
    await expect(page.locator("[data-slot='notification-tenant']")).toHaveText(
      `Tenant ${tenantId}`,
    );
    const record = page.locator("dl[aria-label='Delivery record']");
    await expect(record).toContainText(businessId);
    await expect(record).toContainText(newest.obligation_id);
    await expect(record).not.toContainText(newest.address);
    // Resending is an admin's action, and it waits for its hardened route anyway.
    await expect(page.getByText(/not offered yet/)).toHaveCount(0);
    await checkA11y();
    await page.getByRole("link", { name: "All notifications of this business" }).click();
    await expect(page).toHaveURL(new RegExp(`\\?tenant=${tenantId}&business=${businessId}$`));
  });

  test("an admin opens a notification by its id, names its tenant, and sees what resending waits for", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    const tenantId = seededTenantId() as string;
    const newest = await newestOnService(tenantId, seededBusinessId() as string);
    await signIn(ADMIN);
    await page.goto(`/admin/notifications/${newest.id}`);
    await expect(page.getByRole("heading", { level: 1, name: "Notification" })).toBeVisible();
    const form = page.getByRole("form", { name: "The notification's tenant" });
    await form.getByLabel(/^Tenant id/).fill(tenantId);
    await form.getByRole("button", { name: "Open the notification" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: titleOf(newest.template_key) }),
    ).toBeVisible();
    const awaits = page.locator("[data-slot='resend-awaits']");
    await expect(awaits).toContainText(
      "POST /v1/notification/notifications/{notification_id}/resend",
    );
    await expect(awaits).toContainText("services track (WP30), requiring Idempotency-Key");
    await expect(page.getByRole("button", { name: /resend/i })).toHaveCount(0);
    await checkA11y();

    await page.goto(`/admin/notifications/${randomUUID()}?tenant=${tenantId}`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });

  test("the message templates are listed as the service holds them", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    const response = await fetch(`${serviceUrl("notification")}/v1/notification/templates`);
    expect(response.status).toBe(200);
    const templates = (await response.json()) as TemplateBody[];
    await signIn(REVIEWER);
    await page.goto("/admin/notifications/templates");
    await expect(page.getByRole("heading", { level: 1, name: "Message templates" })).toBeVisible();
    await expect(page.locator("tr[data-template]")).toHaveCount(templates.length);
    const sample = templates[0] as TemplateBody;
    const row = page.locator(
      `tr[data-template='${sample.key}:${sample.channel}:${sample.language}']`,
    );
    await expect(row).toContainText(sample.key);
    await expect(row).toContainText(sample.body.split("\n")[0] as string);
    await checkA11y();
  });

  test("a reviewer gets the not-found page for the console, a tenant role a 404", async ({
    page,
    signIn,
  }) => {
    await signIn(REVIEWER);
    await page.goto("/admin/notifications");
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await signIn(OWNER);
    expect((await page.goto("/admin/notifications"))?.status()).toBe(404);
  });
});
