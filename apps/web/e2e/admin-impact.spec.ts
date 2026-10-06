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
  waitForHydration,
} from "./fixtures";
import { latestVersion } from "./rulebook-helpers";

/**
 * The impact explorer against the engine `make web-stack` starts: an admin's tool, as the engine's
 * dry-run route is. A dry run of a seeded draft and of a specification is run through the page and
 * compared with the engine's answer to the same request. The stack has no worker, so its business
 * directory is empty and every count is zero: the page says nothing was in scope. The product
 * project runs one with businesses in scope.
 */
const PAGE = "/admin/impact";

interface DryRunBody {
  businesses_total: number;
  evaluated: number;
  counts: { applies: number; not_applicable: number; unsure: number };
}

async function dryRunOnEngine(body: unknown): Promise<DryRunBody> {
  const response = await fetch(
    `${serviceUrl("applicability-engine")}/v1/applicability-engine/dry-runs`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  expect(response.status).toBe(200);
  return (await response.json()) as DryRunBody;
}

test.describe("impact explorer", () => {
  test("a tenant role gets a 404, an analyst and a reviewer the not-found page", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
    for (const persona of [ANALYST, REVIEWER]) {
      await signIn(persona);
      await page.goto(PAGE);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
    );

    test("an admin dry-runs a draft and reads the engine's counts", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const draft = await latestVersion(1);
      const expected = await dryRunOnEngine({
        rule_version_id: draft.rule_version_id,
        scope: { sample_size: 5 },
      });
      await signIn(ADMIN);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Impact explorer" }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Impact explorer" })).toBeVisible();
      await checkA11y();
      await waitForHydration(page, "[data-slot='dry-run-form'] input");
      const form = page.getByRole("form", { name: "Run a dry run" });
      await form.getByRole("button", { name: "Run the dry run" }).click();
      await expect(page.getByText("Enter the rule version's id.")).toBeVisible();
      await form.getByLabel(/^Rule version id/).fill(draft.rule_version_id);
      await form.getByLabel(/^Sample decisions/).fill("5");
      await form.getByRole("button", { name: "Run the dry run" }).click();
      const report = page.locator("[data-slot='dry-run-report']");
      await expect(report).toContainText(`${draft.rule_key} (Draft)`);
      await expect(report).toContainText("Every tenant's businesses");
      await expect(report).toContainText(
        `${expected.businesses_total} in scope, ${expected.evaluated} decided`,
      );
      await expect(page.locator("[data-count='applies']")).toContainText(
        String(expected.counts.applies),
      );
      await expect(page.locator("[data-count='not_applicable']")).toContainText(
        String(expected.counts.not_applicable),
      );
      await expect(page.locator("[data-count='unsure']")).toContainText(
        String(expected.counts.unsure),
      );
      if (expected.businesses_total === 0) {
        await expect(
          report.getByRole("heading", { level: 2, name: "No business in scope" }),
        ).toBeVisible();
      }
      await expect(form.getByLabel(/^Rule version id/)).toHaveValue(draft.rule_version_id);
      await checkA11y();
    });

    test("an admin dry-runs a specification at a level, refused first when it is not JSON", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const specification = { attribute: "state_codes", operator: "contains_any", value: ["29"] };
      const expected = await dryRunOnEngine({
        specification,
        scope: { level: "entity", sample_size: 10 },
      });
      await signIn(ADMIN);
      await page.goto(PAGE);
      await waitForHydration(page, "[data-slot='dry-run-form'] select");
      const form = page.getByRole("form", { name: "Run a dry run" });
      await form.getByLabel(/^What to run/).selectOption("specification");
      await form.getByLabel(/^Specification/).fill("[1]");
      await form.getByRole("button", { name: "Run the dry run" }).click();
      await expect(
        page.getByText("Enter the specification as a JSON object of at most 20000 characters."),
      ).toBeVisible();
      await expect(
        page.getByText("Choose the level the specification is decided at."),
      ).toBeVisible();
      await form.getByLabel(/^Specification/).fill(JSON.stringify(specification));
      await form.getByLabel(/^Level/).selectOption("entity");
      await form.getByRole("button", { name: "Run the dry run" }).click();
      const report = page.locator("[data-slot='dry-run-report']");
      await expect(report).toContainText("A specification no version holds");
      await expect(report).toContainText("Legal entities (PAN)");
      await expect(report).toContainText(`${expected.businesses_total} in scope`);
      await checkA11y();
    });

    test("the address names the version to run", async ({ page, signIn }) => {
      const draft = await latestVersion(0);
      await signIn(ADMIN);
      await page.goto(`${PAGE}?rule_version_id=${draft.rule_version_id}`);
      await expect(page.getByLabel(/^Rule version id/)).toHaveValue(draft.rule_version_id);
    });
  });
});
