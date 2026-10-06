import { randomUUID } from "node:crypto";
import { newTenantPersona } from "./business-helpers";
import {
  IS_CI,
  OWNER,
  expect,
  seededTenantId,
  serviceUrl,
  signInThroughForm,
  test,
} from "./fixtures";
import { latestVersion } from "./rulebook-helpers";

/**
 * A CA firm's affected clients against the services `make web-stack` starts. That stack has no
 * worker, so no version is decided for any business: a CA admin of a new firm reads a seeded
 * draft's impact, compared with the engine's (no client, zero counts), every filter says why it
 * is empty, and the bulk change card offers nothing since nobody is affected. The product project
 * sends one to an affected client and sends it again with the same key.
 */
interface ImpactBody {
  counts: { applies: number; not_applicable: number; unsure: number };
  items: unknown[];
}

async function impactOnEngine(tenantId: string, ruleVersionId: string): Promise<ImpactBody> {
  const response = await fetch(
    `${serviceUrl("applicability-engine")}/v1/changes/${ruleVersionId}/impact`,
    { headers: { "x-tenant-id": tenantId } },
  );
  expect(response.status).toBe(200);
  return (await response.json()) as ImpactBody;
}

test.describe("affected clients", () => {
  test("a visitor is sent to sign in, and a business owner to the forbidden page", async ({
    page,
    signIn,
  }) => {
    const path = `/changes/${randomUUID()}/impact`;
    await page.goto(path);
    await expect(page).toHaveURL(/\/sign-in\?next=/);
    await signIn(OWNER);
    await page.goto(path);
    await expect(page).toHaveURL(/\/forbidden$/);
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
    );

    test("a CA admin reads a change no client has a decision of, with nobody to tell", async ({
      page,
      checkA11y,
    }) => {
      const draft = await latestVersion(0);
      const persona = newTenantPersona("ca_firm", ["ca_admin"]);
      const impact = await impactOnEngine(persona.tenantId as string, draft.rule_version_id);
      expect(impact.items).toEqual([]);
      const path = `/changes/${draft.rule_version_id}/impact`;
      await signInThroughForm(page, persona, path);
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Affected clients" })).toBeVisible();
      const name = `${draft.rule_key} v${draft.version}`;
      await expect(
        page.getByText(`Which of your clients ${name} affects: ${draft.title}`),
      ).toBeVisible();
      await expect(page.locator("[data-slot='change-facts']")).toContainText(`${name} is Draft.`);
      await expect(page.locator("[data-count='applies']")).toContainText(
        String(impact.counts.applies),
      );
      await expect(
        page.getByRole("heading", { level: 2, name: "No client is affected" }),
      ).toBeVisible();
      await expect(page.locator("[data-slot='bulk-nobody']")).toHaveText(
        "No client is affected, so there is nobody to tell.",
      );
      await expect(page.getByRole("button", { name: /Send the change card/ })).toHaveCount(0);
      await expect(page.getByRole("complementary", { name: "Not legal advice" })).toBeVisible();
      await checkA11y();

      const filters = page.getByRole("navigation", { name: "Show clients by result" });
      await filters.getByRole("link", { name: "Every client" }).click();
      await expect(page).toHaveURL(new RegExp(`${path}\\?result=all$`));
      await expect(
        page.getByRole("heading", { level: 2, name: "No client has a decision of this change" }),
      ).toBeVisible();
      await expect(filters.getByRole("link", { name: "Every client" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      await checkA11y();
    });

    test("an unknown and a malformed version are the not-found page", async ({ page }) => {
      const persona = newTenantPersona("ca_firm", ["ca_staff"]);
      await signInThroughForm(page, persona);
      for (const id of [randomUUID(), "not-a-version"]) {
        await page.goto(`/changes/${id}/impact`);
        await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
      }
    });
  });
});
