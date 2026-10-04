import { randomUUID } from "node:crypto";
import { formatDate, todayKey } from "../src/shared/lib/dates.ts";
import { ANALYST, IS_CI, OWNER, expect, seededTenantId, test, waitForHydration } from "./fixtures";
import {
  conditionAttributes,
  latestVersion,
  ruleKeys,
  rulebookGet,
  versionsOf,
  type VersionRow,
} from "./rulebook-helpers";

/**
 * The rule version list and a version's page against the rulebook `make web-stack` starts with
 * the seed calendar's drafts. These specs only read; the publish spec moves other drafts, so the
 * assertions here hold whatever state those are in.
 */
const LIST = "/admin/rulebook/versions";

test.describe("rule versions", () => {
  test("a tenant role gets a 404 for the list and a version", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of [LIST, `${LIST}/${randomUUID()}`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed version id is the not-found page", async ({ page, signIn, checkA11y }) => {
    await signIn(ANALYST);
    await page.goto(`${LIST}/not-a-version`);
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

    test("opens from the sidebar in force today, then lists the drafts and every version", async ({
      page,
      checkA11y,
    }) => {
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Rule versions" }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Rule versions" })).toBeVisible();
      await expect(
        page.locator("aside").getByRole("link", { name: "Rule versions" }),
      ).toHaveAttribute("aria-current", "page");
      const today = todayKey();
      const inForce = await rulebookGet<VersionRow[]>(
        `/v1/rulebook/rule-versions?as_of=${today}&limit=500`,
      );
      if (inForce.length === 0) {
        await expect(
          page.getByRole("heading", { name: `No version is in force on ${formatDate(today)}` }),
        ).toBeVisible();
      } else {
        await expect(page.locator("[data-slot='versions-table'] tbody tr")).toHaveCount(
          Math.min(inForce.length, 25),
        );
      }
      await checkA11y();

      const chips = page.getByRole("navigation", { name: "Show versions by status" });
      await chips.getByRole("link", { name: "Draft", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}\\?status=draft$`));
      await expect(chips.getByRole("link", { name: "Draft", exact: true })).toHaveAttribute(
        "aria-current",
        "true",
      );
      const keys = await ruleKeys();
      // The first two rules are left alone by every spec, so they are drafts on any run.
      for (const key of keys.slice(0, 2)) {
        const [draft] = (await versionsOf(key)).filter((version) => version.status === "draft");
        if (draft === undefined) throw new Error(`${key} has no draft`);
        const row = page.locator(`[data-rule-version='${draft.rule_version_id}']`);
        await expect(row).toBeVisible();
        await expect(row.getByRole("link", { name: `${key} v${draft.version}` })).toBeVisible();
        await expect(row).toContainText("Not yet reviewed");
        await expect(row).toContainText(draft.title);
      }
      for (const row of await page.locator("[data-slot='versions-table'] tbody tr").all()) {
        await expect(row).toHaveAttribute("data-status", "draft");
      }
      await checkA11y();

      await chips.getByRole("link", { name: "Every status" }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}\\?status=all$`));
      const every = (await Promise.all(keys.map((key) => versionsOf(key)))).flat();
      await expect(page.locator("[data-slot='versions-table'] tbody tr")).toHaveCount(every.length);
    });

    test("filters by one rule and opens its draft with the condition in words", async ({
      page,
      checkA11y,
    }) => {
      const draft = await latestVersion(0);
      await page.goto(`${LIST}?status=draft`);
      await waitForHydration(page, "[data-slot='version-filter'] select");
      await page.getByLabel("Rule", { exact: true }).selectOption(draft.rule_key);
      await page.getByRole("button", { name: "Show versions" }).click();
      await expect(page).toHaveURL(new RegExp(`status=draft&rule=${draft.rule_key}$`));
      const rows = page.locator("[data-slot='versions-table'] tbody tr");
      await expect(rows).toHaveCount(1);
      await rows.getByRole("link", { name: `${draft.rule_key} v${draft.version}` }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}/${draft.rule_version_id}$`));
      await expect(page.getByRole("heading", { level: 1, name: draft.title })).toBeVisible();
      await expect(
        page
          .getByRole("navigation", { name: "Breadcrumb" })
          .getByText(`${draft.rule_key} v${draft.version}`),
      ).toBeVisible();
      await expect(page.locator("[data-notice='not-reviewed']")).toContainText("Not yet reviewed");
      const facts = page.locator("[data-slot='version-facts']");
      await expect(facts).toContainText(formatDate(draft.effective_from));
      await expect(facts).toContainText("Draft");
      for (const attribute of conditionAttributes(draft.specification)) {
        await expect(
          page.locator(`[data-slot='spec-predicate'][data-attribute='${attribute}']`).first(),
        ).toBeVisible();
      }
      for (const question of draft.todo) {
        await expect(page.locator("[data-slot='questions']")).toContainText(question);
      }
      await expect(page.getByRole("heading", { level: 2, name: "Citations" })).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: "Publish workflow" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Submit for review" })).toBeVisible();
      await checkA11y();
    });

    test("an unknown version id is the not-found page", async ({ page }) => {
      await page.goto(`${LIST}/${randomUUID()}`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
      await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute(
        "content",
        /noindex/,
      );
    });
  });
});
