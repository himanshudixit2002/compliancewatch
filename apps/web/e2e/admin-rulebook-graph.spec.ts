import { randomUUID } from "node:crypto";
import { ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import { latestVersion, rulebookGet } from "./rulebook-helpers";

/**
 * The relations graph against the rulebook the stack runs. A seeded draft has the relations an
 * analyst gave it (none on a fresh stack), so the graph is compared with the rulebook's own
 * relations from and to the version rather than with a number. Read-only.
 */
const TOOL = "/admin/rulebook/relations/graph";

test.describe("relations graph", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(TOOL))?.status()).toBe(404);
  });

  test("asks for a version and refuses a malformed id on its field", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto(TOOL);
    await expect(page.getByRole("heading", { level: 1, name: "Relations graph" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Choose a rule version to start from" }),
    ).toBeVisible();
    await checkA11y();
    await page.goto(`${TOOL}?rule_version_id=not-a-version`);
    await expect(page.getByText("This is not a rule version id (a UUID).")).toBeVisible();
    await expect(page.getByLabel(/^Rule version id/)).toHaveValue("not-a-version");
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test.beforeEach(async ({ signIn }) => {
      await signIn(ANALYST);
    });

    test("opens from a version's page, draws it and lists its relations as the rulebook holds them", async ({
      page,
      checkA11y,
    }) => {
      const version = await latestVersion(1);
      await page.goto(`/admin/rulebook/versions/${version.rule_version_id}`);
      await page.getByRole("link", { name: "Open the relations graph" }).click();
      await expect(page).toHaveURL(
        new RegExp(`${TOOL}\\?rule_version_id=${version.rule_version_id}$`),
      );
      await expect(
        page.getByRole("heading", {
          name: `Around ${version.rule_key} v${version.version}: ${version.title}`,
        }),
      ).toBeVisible();
      const picture = page.locator("[data-slot='graph-picture'] svg");
      await expect(picture).toHaveAttribute("aria-hidden", "true");
      await expect(picture.locator(`[data-node='version:${version.rule_version_id}']`)).toHaveCount(
        1,
      );
      const query = "published_only=false&limit=200";
      const [from, to] = await Promise.all([
        rulebookGet<{ relation_id: string }[]>(
          `/v1/rulebook/relations?from_rule_version_id=${version.rule_version_id}&${query}`,
        ),
        rulebookGet<{ relation_id: string }[]>(
          `/v1/rulebook/relations?to_rule_version_id=${version.rule_version_id}&${query}`,
        ),
      ]);
      const relations = new Set([...from, ...to].map((relation) => relation.relation_id));
      if (relations.size === 0) {
        await expect(
          page.getByRole("heading", { name: "No relation from or to this version" }),
        ).toBeVisible();
      } else {
        await expect(page.locator("[data-slot='graph-table'] tbody tr")).toHaveCount(
          relations.size,
        );
      }
      await checkA11y();
    });

    test("answers a version the rulebook does not hold on the field", async ({ page }) => {
      const unknown = randomUUID();
      await page.goto(`${TOOL}?rule_version_id=${unknown}&depth=2`);
      await expect(
        page.getByText("The rulebook holds no rule version with this id."),
      ).toBeVisible();
      await expect(page.getByLabel(/^Rule version id/)).toHaveValue(unknown);
      await expect(page.getByLabel("Relations out")).toHaveValue("2");
    });
  });
});
