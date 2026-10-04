import { ANALYST, IS_CI, OWNER, expect, seededTenantId, serviceUrl, test } from "./fixtures";

/**
 * The ontology browser against the profile service's GET /v1/ontology: the page is compared with
 * the body the service returns, so no wording is restated here. It only reads, so it runs in
 * parallel and again on the same stack.
 */
interface OntologyBody {
  version: string;
  attributes: {
    key: string;
    level: string;
    question: string;
    values: { value: string; label: string }[];
  }[];
}

async function ontologyFromService(): Promise<OntologyBody> {
  const response = await fetch(`${serviceUrl("profile")}/v1/ontology`);
  expect(response.status, "GET /v1/ontology on the stack").toBe(200);
  return (await response.json()) as OntologyBody;
}

const LEVELS: Readonly<Record<string, string>> = {
  entity: "Legal entity (PAN)",
  registration: "Registration (GSTIN)",
  location: "Location",
};

test.describe("ontology browser", () => {
  test("an analyst reads every attribute by level, as the profile service serves it", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );
    const ontology = await ontologyFromService();
    await signIn(ANALYST);
    await page.goto("/admin");
    await page.locator("aside").getByRole("link", { name: "Ontology" }).click();
    await expect(page).toHaveURL(/\/admin\/ontology$/);
    await expect(page.getByRole("heading", { level: 1, name: "Ontology" })).toBeVisible();
    await expect(page.locator("dl[aria-label='About this ontology']")).toContainText(
      ontology.version,
    );
    const usage = page.locator("[data-slot='usage-awaits']");
    await expect(usage).toContainText("GET /v1/profile/admin/attribute-usage");
    await expect(usage).toContainText("services track (WP30)");

    const levels = [...new Set(ontology.attributes.map((attribute) => attribute.level))];
    for (const level of levels) {
      await expect(page.getByRole("heading", { level: 2, name: LEVELS[level] })).toBeVisible();
    }
    await expect(page.locator("tr[data-attribute]")).toHaveCount(ontology.attributes.length);
    for (const attribute of ontology.attributes) {
      const row = page.locator(
        `[data-level='${attribute.level}'] tr[data-attribute='${attribute.key}']`,
      );
      await expect(row).toContainText(attribute.key);
      await expect(row).toContainText(
        attribute.question.trim() === "" ? "Not asked" : attribute.question.trim(),
      );
      for (const option of attribute.values) await expect(row).toContainText(option.label);
    }
    await checkA11y();
  });

  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto("/admin/ontology"))?.status()).toBe(404);
  });
});
