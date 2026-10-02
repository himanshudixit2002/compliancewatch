import {
  createBusinessOnService,
  examplePan,
  newTenantPersona,
  seededBusinessId,
} from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * The businesses list against the real profile service: the seeded owner with one business goes
 * straight to it, a new tenant sees why the list is empty, and a CA firm with more clients than a
 * page holds searches and pages through them. Each CA test works in a tenant of its own.
 */
test.describe("businesses list", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an owner with one business goes straight to it", async ({ page }) => {
    const tenantId = seededTenantId();
    const businessId = seededBusinessId();
    expect(businessId, "make web-seed writes var/seed/last.json").not.toBeNull();
    await signInThroughForm(page, {
      ...newTenantPersona(),
      tenantId: tenantId as string,
    });
    await page.goto("/businesses");
    await expect(page).toHaveURL(new RegExp(`/b/${businessId}$`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("a new owner sees why the list is empty and where to start", async ({ page, checkA11y }) => {
    await signInThroughForm(page, newTenantPersona());
    await page.goto("/businesses");
    await expect(page.getByRole("heading", { level: 1, name: "Businesses" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "No business yet" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Get started" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
    await expect(page.getByRole("link", { name: "Add a business" })).toHaveAttribute(
      "href",
      "/onboarding/business",
    );
    await checkA11y();
  });

  test("a CA firm searches its clients and pages through them", async ({ page, checkA11y }) => {
    test.setTimeout(60_000);
    const persona = newTenantPersona("ca_firm", ["ca_admin"]);
    const tenantId = persona.tenantId as string;
    for (let n = 1; n <= 22; n += 1) {
      await createBusinessOnService(tenantId, {
        name: `Example Client ${String(n).padStart(2, "0")}`,
        pan: examplePan(n),
      });
    }
    await createBusinessOnService(tenantId, {
      name: "Example Gstin Client",
      gstin: "27ABCDE1234F1Z5",
    });

    await signInThroughForm(page, persona);
    await page.goto("/businesses");
    await expect(page).toHaveURL(/\/businesses$/);
    await expect(page.getByRole("heading", { level: 1, name: "Clients" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add a client" })).toBeVisible();
    const status = page.locator("[data-slot='directory-status']");
    await expect(status).toHaveText("Page 1: 20 clients.");
    const rows = page
      .getByRole("table", { name: "Client businesses of your firm" })
      .locator("tbody tr");
    await expect(rows).toHaveCount(20);
    await expect(rows.first()).toContainText("Example Client 01");
    await checkA11y();

    await page.getByRole("button", { name: "Next page" }).click();
    await expect(status).toHaveText("Page 2: 3 clients.");
    await expect(status).toBeFocused();
    await expect(rows).toHaveCount(3);
    await expect(page.getByRole("button", { name: "Next page" })).toHaveCount(0);
    await page.getByRole("button", { name: "First page" }).click();
    await expect(status).toHaveText("Page 1: 20 clients.");

    // A term in the POST body, never in the URL: a name, a PAN, a GSTIN.
    const search = page.getByRole("textbox", { name: /Search/ });
    await search.fill("client 07");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(status).toHaveText('Page 1: 1 matching "client 07".');
    await expect(rows).toHaveCount(1);
    await expect(page).toHaveURL(/\/businesses$/);
    await search.fill(examplePan(12).toLowerCase());
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(rows).toHaveText([/Example Client 12/]);
    await search.fill("27ABCDE1234F1Z5");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(rows).toHaveText([/Example Gstin Client/]);
    await search.fill("no such client");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Nothing matches the search" })).toBeVisible();
    await checkA11y();

    await search.fill("client 1");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByRole("link", { name: "Example Client 10" }).click();
    await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Example Client 10" })).toBeVisible();
  });

  test("a compliance lead reads the list but is not offered to add a business", async ({
    page,
  }) => {
    const persona = newTenantPersona("business", ["compliance_lead"]);
    const tenantId = persona.tenantId as string;
    await createBusinessOnService(tenantId, { name: "Example One", pan: examplePan(1) });
    await createBusinessOnService(tenantId, { name: "Example Two", pan: examplePan(2) });
    await signInThroughForm(page, persona);
    await page.goto("/businesses");
    await expect(page.getByRole("heading", { level: 1, name: "Businesses" })).toBeVisible();
    await expect(page.locator("[data-slot='directory-status']")).toHaveText(
      "Page 1: 2 businesses.",
    );
    await expect(page.getByRole("link", { name: "Add a business" })).toHaveCount(0);
  });
});
