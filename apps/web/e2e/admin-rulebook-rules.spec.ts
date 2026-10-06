import { ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import { ruleKeys } from "./rulebook-helpers";

/**
 * The rule list against the rulebook the stack starts with the seed calendar's drafts: every
 * rule the rulebook lists, the filter typed over them and the way to a rule's versions. It only
 * reads, so it runs in parallel and again on the same stack.
 */
const PAGE = "/admin/rulebook/rules";

test.describe("rules", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
  });

  test("an analyst reads every rule, filters them and opens one rule's versions", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );
    const keys = await ruleKeys();
    await signIn(ANALYST);
    await page.goto("/admin");
    await page.locator("aside").getByRole("link", { name: "Rules", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
    await expect(page.getByRole("heading", { level: 1, name: "Rules" })).toBeVisible();
    const rows = page.locator("tr[data-rule]");
    await expect(rows).toHaveCount(keys.length);
    expect(
      await rows.evaluateAll((elements) => elements.map((row) => row.getAttribute("data-rule"))),
    ).toEqual(keys);
    await expect(page.getByText(`${keys.length} of ${keys.length} rules shown.`)).toBeVisible();
    await checkA11y();

    const key = keys[0] as string;
    await page.getByLabel(/^Filter the rules/).fill(key);
    await expect(page.locator(`tr[data-rule='${key}']`)).toBeVisible();
    for (const row of await rows.all()) {
      await expect(row).toContainText(key);
    }
    await page.getByRole("link", { name: `Every version of ${key}` }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/rulebook/versions\\?status=all&rule=${key}$`));
    await expect(page.getByRole("heading", { level: 1, name: "Rule versions" })).toBeVisible();
  });
});
