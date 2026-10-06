import { randomUUID } from "node:crypto";
import {
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
 * The decision review queue against the engine `make web-stack` starts. The review routes act for
 * the tenant named in x-tenant-id, so the screen is a lookup by tenant; the seeded tenant's items
 * are read from the engine first and the page compared with them. The stack's rulebook holds only
 * drafts and no seed rule has a condition in words, so the queue is empty there: settling an item
 * is covered by the unit tests, and the page's empty states, its lookup and its gate here.
 */
const PAGE = "/admin/decisions";

async function itemsOnEngine(tenantId: string, status?: string): Promise<{ item_id: string }[]> {
  const query = status === undefined ? "" : `?status=${status}`;
  const response = await fetch(
    `${serviceUrl("applicability-engine")}/v1/applicability-engine/review-items${query}`,
    { headers: { "x-tenant-id": tenantId } },
  );
  expect(response.status).toBe(200);
  return ((await response.json()) as { items: { item_id: string }[] }).items;
}

test.describe("decision review", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
    );

    test("an analyst looks the seeded tenant up and reads its queue as the engine lists it", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const tenantId = seededTenantId() as string;
      const open = await itemsOnEngine(tenantId, "open");
      const every = await itemsOnEngine(tenantId);
      await signIn(ANALYST);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Decision review" }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Decision review" })).toBeVisible();
      await expect(page.getByText(/Give a tenant's id/)).toBeVisible();
      await checkA11y();

      const lookup = page.getByRole("form", { name: "Look up a tenant's review items" });
      await lookup.getByLabel(/^Tenant id/).fill("not-a-tenant");
      await lookup.getByRole("button", { name: "Show the items" }).click();
      await expect(page.getByText("Enter the tenant's id, a UUID.")).toBeVisible();
      await expect(page.getByLabel(/^Tenant id/)).toHaveValue("not-a-tenant");

      await page.getByLabel(/^Tenant id/).fill(tenantId);
      await page.getByRole("button", { name: "Show the items" }).click();
      await expect(page).toHaveURL(new RegExp(`\\?tenant=${tenantId}&status=open$`));
      await expect(
        page.getByRole("heading", { level: 2, name: "Review items of the tenant" }),
      ).toBeVisible();
      await expect(page.locator("[data-slot='lookup-facts']")).toHaveText(
        `Tenant ${tenantId}, Open`,
      );
      if (open.length === 0) {
        await expect(
          page.getByRole("heading", { level: 2, name: "Nothing waits for a reviewer" }),
        ).toBeVisible();
      } else {
        await expect(page.locator("article[data-review-item]")).toHaveCount(open.length);
        // Settling is a reviewer's or an admin's; an analyst reads.
        await expect(page.getByRole("button", { name: "Settle the item" })).toHaveCount(0);
      }
      await checkA11y();

      await page.getByLabel("Items", { exact: true }).selectOption("all");
      await page.getByRole("button", { name: "Show the items" }).click();
      await expect(page).toHaveURL(new RegExp(`\\?tenant=${tenantId}&status=all$`));
      if (every.length === 0) {
        await expect(page.getByRole("heading", { level: 2, name: "No review item" })).toBeVisible();
      } else {
        await expect(page.locator("article[data-review-item]")).toHaveCount(every.length);
      }
    });

    test("a reviewer opens the queue of a tenant with no item", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const tenantId = randomUUID();
      await signIn(REVIEWER);
      await page.goto(`${PAGE}?tenant=${tenantId}&status=resolved`);
      await expect(page.getByLabel("Items", { exact: true })).toHaveValue("resolved");
      await expect(
        page.getByRole("heading", { level: 2, name: "No item has been settled" }),
      ).toBeVisible();
      await checkA11y();
    });
  });
});
