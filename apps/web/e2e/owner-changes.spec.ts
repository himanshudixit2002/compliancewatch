import { randomUUID } from "node:crypto";
import {
  createBusinessOnService,
  examplePan,
  newTenantPersona,
  seededBusinessId,
} from "./business-helpers";
import { IS_CI, expect, seededTenantId, serviceUrl, signInThroughForm, test } from "./fixtures";

/**
 * The changes feed of a business against the services `make web-stack` starts. That stack's
 * rulebook starts with drafts only and no spec publishes one, so the feed is read from the
 * service first: empty, the page says nothing is published yet; otherwise the newest change is
 * shown as not decided for a business no fan-out has seen. The product project shows a change
 * that applies.
 */
interface FeedItem {
  change_id: string;
  title: string;
}

async function feedOnService(): Promise<FeedItem[]> {
  const response = await fetch(`${serviceUrl("rulebook")}/v1/changes?limit=20`);
  expect(response.status).toBe(200);
  return ((await response.json()) as { items: FeedItem[] }).items;
}

test.describe("changes", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("a business reads the published changes, or why there are none", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: "Example Changes Ltd",
      pan: examplePan(21),
    });
    const feed = await feedOnService();
    await signInThroughForm(page, persona, `/b/${business.id}`);
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await tabs.getByRole("link", { name: "Changes", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${business.id}/changes$`));
    await expect(page.getByRole("heading", { level: 1, name: "Changes" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(
      "Example Changes Ltd",
    );
    const newest = feed[0];
    if (newest === undefined) {
      await expect(
        page.getByRole("heading", { level: 2, name: "No published changes yet" }),
      ).toBeVisible();
    } else {
      const card = page.locator(`article[data-change='${newest.change_id}']`);
      await expect(card.getByRole("heading", { level: 2 })).toHaveText(newest.title);
      // A business made just now was in no fan-out: nothing is decided for it.
      await expect(card).toHaveAttribute("data-applicability", "not_decided");
      await expect(card).toContainText("Not decided for this business");
    }
    await expect(page.getByRole("complementary", { name: "Not legal advice" })).toBeVisible();
    await checkA11y();
  });

  test("another tenant's business, an unknown one and a malformed id are not found", async ({
    page,
  }) => {
    const persona = newTenantPersona();
    await signInThroughForm(page, persona);
    for (const id of [seededBusinessId() as string, randomUUID(), "not-an-id"]) {
      await page.goto(`/b/${id}/changes`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });

  test("a visitor is sent to sign in first", async ({ page }) => {
    await page.goto(`/b/${randomUUID()}/changes`);
    await expect(page).toHaveURL(/\/sign-in\?next=/);
  });
});
