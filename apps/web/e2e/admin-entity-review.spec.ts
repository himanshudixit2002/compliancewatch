import { ANALYST, IS_CI, OWNER, REVIEWER, expect, seededTenantId, test } from "./fixtures";
import { rulebookGet, stageReview } from "./rulebook-helpers";

/**
 * The entity review queue and a group's page against the rulebook the stack runs (`make
 * web-seed` registers the recorded notification, whose mentions open five groups), with
 * web.admin_rulebook_writes on for the run (playwright.config.ts). The reading tests compare the
 * pages with the rulebook's own answers; the deciding test stages a synthetic document of its own
 * (two groups named for the run) and decides those, so the specs run in parallel and again on the
 * same stack without touching the recorded notification's groups.
 */
const QUEUE = "/admin/rulebook/entities";
const GROUP = "/admin/rulebook/entities/group";

interface GroupRow {
  entity_type: string;
  proposed_name: string;
  open_count: number;
  examples: { document_id: string; clause_id: string; span_start: number; span_end: number }[];
}

interface ItemRow {
  review_id: string;
  mention_text: string;
}

function groupHref(type: string, name: string): string {
  return `${GROUP}?${new URLSearchParams({ type, name }).toString()}`;
}

test.describe("entity review", () => {
  test("a tenant role gets a 404 for the queue and a group", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of [QUEUE, groupHref("form", "EX-1")]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a group page without a group, or with a type the rulebook does not know, says so", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto(GROUP);
    await expect(page.getByRole("heading", { level: 1, name: "Entity group" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No group is named" })).toBeVisible();
    await checkA11y();
    await page.goto(groupHref("example", "EX-1"));
    await expect(page.getByText("This address does not name a group")).toBeVisible();
    await expect(
      page.getByText('"example" is not an entity type the rulebook knows.'),
    ).toBeVisible();
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test("lists the open groups, and one type of them as the rulebook holds it", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await signIn(ANALYST);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Entity review", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${QUEUE}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Entity review" })).toBeVisible();
      const rows = page.locator("[data-slot='entity-group-row']");
      await expect(rows.first()).toBeVisible();
      await checkA11y();

      // Sections: the recorded notification's own groups, which no spec stages or decides.
      await page.getByLabel("Entity type").selectOption("section");
      await page.getByRole("button", { name: "Show groups" }).click();
      await expect(page).toHaveURL(new RegExp(`${QUEUE}\\?type=section$`));
      const sections = await rulebookGet<GroupRow[]>(
        "/v1/rulebook/review/entities?entity_type=section&limit=25",
      );
      expect(sections.length, "the recorded notification names sections").toBeGreaterThan(0);
      // The rows stream in under the loading skeleton: wait for them before reading them.
      await expect(rows).toHaveCount(sections.length);
      const shown = await rows.evaluateAll((elements) =>
        elements.map((element) => element.getAttribute("data-group")),
      );
      expect(shown).toEqual(sections.map((group) => `section:${group.proposed_name}`));
      for (const group of sections) {
        await expect(rows.filter({ hasText: group.proposed_name }).first()).toContainText(
          String(group.open_count),
        );
      }
      await checkA11y();
    });

    test("opens a group from the queue: its mentions, each shown in its document", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const [group] = await rulebookGet<GroupRow[]>(
        "/v1/rulebook/review/entities?entity_type=section&limit=1",
      );
      if (group === undefined) throw new Error("the recorded notification names no section");
      await signIn(REVIEWER);
      await page.goto(`${QUEUE}?type=section`);
      await page.getByRole("link", { name: group.proposed_name, exact: true }).click();
      await expect(page).toHaveURL((url) =>
        url.href.endsWith(groupHref("section", group.proposed_name)),
      );
      await expect(page.getByRole("heading", { level: 1, name: "Entity group" })).toBeVisible();
      const items = await rulebookGet<ItemRow[]>(
        `/v1/rulebook/review/entities/items?${new URLSearchParams({
          entity_type: "section",
          proposed_name: group.proposed_name,
        }).toString()}`,
      );
      await expect(page.locator("[data-review-id]")).toHaveCount(items.length);
      await expect(page.locator("[data-slot='group-facts']")).toContainText(group.proposed_name);
      await expect(
        page.getByRole("link", { name: "See how this name resolves among the canonical entities" }),
      ).toBeVisible();
      await checkA11y();

      const first = items[0];
      if (first === undefined) throw new Error("the group has no open mention");
      await page
        .locator(`[data-review-id='${first.review_id}']`)
        .getByRole("link", { name: "Show in the document" })
        .click();
      await expect(page).toHaveURL(
        /\/admin\/rulebook\/documents\/.+\?clause_id=.+&start=\d+&end=\d+$/,
      );
      await expect(page.locator("mark")).toHaveText(first.mention_text);
    });

    test("rejects one group with a reason and makes the entity of another", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageReview(2);
      const [rejected, made] = staged.names as [string, string];
      await signIn(ANALYST);

      await page.goto(groupHref("form", rejected));
      await expect(page.getByRole("heading", { level: 2, name: "Decide the group" })).toBeVisible();
      await page.getByRole("radio", { name: "Reject the mentions" }).click();
      await page.getByLabel(/^Why reject/).selectOption("not_an_entity");
      await page.getByLabel(/^Note/).fill("Example note: staged by the e2e run");
      await page.getByRole("button", { name: "Record the decision" }).click();
      const dialog = page.getByRole("dialog", { name: `Decide ${rejected}?` });
      await expect(dialog).toContainText("as rejected (Not an entity)");
      await checkA11y();
      await dialog.getByRole("button", { name: "Record the decision" }).click();
      await expect(page.locator("[data-slot='decision-done']")).toContainText(
        "Decision recorded. Mentions closed: 1.",
      );
      await expect(
        page.getByRole("heading", { name: "Every mention of this group is decided" }),
      ).toBeVisible();
      expect(
        await rulebookGet<ItemRow[]>(
          `/v1/rulebook/review/entities/items?entity_type=form&proposed_name=${rejected}`,
        ),
      ).toEqual([]);
      await checkA11y();

      await page.goto(groupHref("form", made));
      await page.getByRole("checkbox", { name: `Include the mention ${made}` }).check();
      await expect(page.getByText("The decision covers the included mentions (1).")).toBeVisible();
      await page.getByRole("radio", { name: "Make the entity" }).click();
      await page.getByRole("button", { name: "Record the decision" }).click();
      await page
        .getByRole("dialog", { name: `Decide ${made}?` })
        .getByRole("button", { name: "Record the decision" })
        .click();
      const done = page.locator("[data-slot='decision-done']");
      await expect(done).toContainText("A new entity was made");
      const resolution = await rulebookGet<{
        status: string;
        entity: { entity_id: string } | null;
      }>(`/v1/rulebook/entities/resolve?type=form&name=${made}`);
      expect(resolution.status).toBe("resolved");
      const entityId = resolution.entity?.entity_id ?? "";
      await done.getByRole("link", { name: entityId }).click();
      await expect(page).toHaveURL(new RegExp(`/admin/rulebook/entities/canonical/${entityId}$`));
      await expect(page.getByText(made).first()).toBeVisible();
    });
  });
});
