import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import { rulebookGet } from "./rulebook-helpers";

/**
 * The resolve tool and an entity's page against the rulebook the stack runs. A fresh stack holds
 * no canonical entity (one is created only when an analyst decides a review group, as the entity
 * review spec does for names of its own), so the names below resolve as the rulebook says (the
 * specs compare each answer with the service's) and an entity's page is opened when one resolves.
 */
const TOOL = "/admin/rulebook/entities/canonical";

const STATUS_LABELS: Readonly<Record<string, string>> = {
  resolved: "Resolved",
  ambiguous: "Ambiguous",
  not_found: "Not found",
  unqualified: "Unqualified",
  empty: "Empty",
};

interface Resolution {
  status: string;
  normalised: string;
  entity: { entity_id: string; canonical_name: string } | null;
  candidates: { entity_id: string }[];
}

const MENTIONS = JSON.parse(
  readFileSync(
    resolve(__dirname, "../scripts/seed/fixtures/rulebook/gst-ct-01-2026.mentions.json"),
    "utf8",
  ),
) as { mentions: { entity_type: string; text: string }[] };

test.describe("canonical entities", () => {
  test("a tenant role gets a 404 for the tool and an entity", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of [TOOL, `${TOOL}/${randomUUID()}`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed entity id is the not-found page", async ({ page, signIn, checkA11y }) => {
    await signIn(ANALYST);
    await page.goto(`${TOOL}/not-an-entity`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute("content", /noindex/);
    await checkA11y();
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test.beforeEach(async ({ signIn }) => {
      await signIn(ANALYST);
    });

    test("opens from the sidebar and resolves names as the rulebook does", async ({
      page,
      checkA11y,
    }) => {
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Canonical entities" }).click();
      await expect(page).toHaveURL(new RegExp(`${TOOL}$`));
      await expect(
        page.getByRole("heading", { level: 1, name: "Canonical entities" }),
      ).toBeVisible();
      await checkA11y();

      const form = MENTIONS.mentions.find((mention) => mention.entity_type === "form");
      if (form === undefined) throw new Error("the recorded mentions name no form");
      const names: [string, string][] = [
        ["form", form.text],
        ["section", "39"],
        ["hsn_code", "Example code"],
      ];
      for (const [type, name] of names) {
        await page.getByLabel("Entity type").selectOption(type);
        await page.getByLabel(/^Name/).fill(name);
        await page.getByRole("button", { name: "Resolve" }).click();
        await expect
          .poll(() => {
            const url = new URL(page.url());
            return [url.searchParams.get("type"), url.searchParams.get("name")];
          })
          .toEqual([type, name]);
        const answer = await rulebookGet<Resolution>(
          `/v1/rulebook/entities/resolve?type=${type}&name=${encodeURIComponent(name)}`,
        );
        const result = page.locator("[data-slot='resolution']");
        await expect(result).toHaveAttribute("data-status", answer.status);
        await expect(result).toContainText(STATUS_LABELS[answer.status] ?? answer.status);
        await expect(result.locator("[data-slot='normalised'] code")).toHaveText(
          answer.normalised === "" ? "(nothing)" : answer.normalised,
        );
        const choices = answer.entity === null ? answer.candidates.length : 1;
        await expect(result.locator("[data-slot='entity-choices'] li")).toHaveCount(choices);
        await checkA11y();
      }
    });

    test("refuses a blank name on its field and keeps the type", async ({ page }) => {
      await page.goto(`${TOOL}?type=rule&name=`);
      await expect(page.getByText("Enter the name to resolve.")).toBeVisible();
      await expect(page.getByLabel("Entity type")).toHaveValue("rule");
      await expect(page.locator("[data-slot='resolution']")).toHaveCount(0);
    });

    test("opens the entity a resolved name points at, when the rulebook holds one", async ({
      page,
      checkA11y,
    }) => {
      const form = MENTIONS.mentions.find((mention) => mention.entity_type === "form");
      if (form === undefined) throw new Error("the recorded mentions name no form");
      const answer = await rulebookGet<Resolution>(
        `/v1/rulebook/entities/resolve?type=form&name=${encodeURIComponent(form.text)}`,
      );
      test.skip(answer.entity === null, "no analyst has created this entity on this stack");
      const entity = answer.entity as { entity_id: string; canonical_name: string };
      await page.goto(`${TOOL}?type=form&name=${encodeURIComponent(form.text)}`);
      await page.locator("[data-slot='entity-choices'] a").first().click();
      await expect(page).toHaveURL(new RegExp(`${TOOL}/${entity.entity_id}$`));
      await expect(
        page.getByRole("heading", { level: 1, name: entity.canonical_name }),
      ).toBeVisible();
      const clauses = await rulebookGet<unknown[]>(
        `/v1/rulebook/entities/${entity.entity_id}/clauses?limit=50`,
      );
      await expect(page.locator("[data-slot='mentioned-clauses'] > li")).toHaveCount(
        clauses.length,
      );
      await checkA11y();
    });

    test("an unknown entity id is the not-found page", async ({ page }) => {
      await page.goto(`${TOOL}/${randomUUID()}`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    });
  });
});
