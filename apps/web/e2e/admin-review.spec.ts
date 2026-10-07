import {
  ANALYST,
  IS_CI,
  REVIEWER,
  expect,
  seededTenantId,
  test,
  waitForHydration,
} from "./fixtures";
import {
  expectQueueShown,
  openSeedTasks,
  reviewStats,
  taskDetail,
  undecidedTaskOf,
  type StatsBody,
} from "./review-helpers";
import { latestVersion } from "./rulebook-helpers";

/**
 * The review queue against the rulebook `make web-stack` starts with the seed calendar's drafts.
 * Every task there is a seed task over one of those drafts; the workbench specs claim, edit and
 * decide the tasks of drafts they own (D-063) while this spec runs, so it compares the page with
 * the rulebook's queue read either side of it rather than with counts taken once. It opens the
 * seed tasks (idempotent), reads the queue in the rulebook's order through every filter, compares
 * the strip with the stats and drives the keyboard.
 */
const EITHER_ANSWER =
  /^(Review tasks opened for seed drafts: \d+\.|Every seed draft that needs review already has a task: nothing was opened\.)$/;
test.describe("the review queue", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test.beforeEach(async ({ signIn }) => {
    await signIn(ANALYST);
  });

  test("opens the seed tasks, and pressing again opens no second task for a draft", async ({
    page,
    checkA11y,
  }) => {
    // Other specs decide tasks meanwhile, and a rejected or returned draft gets a task on the next
    // press, so either answer may come back each time; what must hold is one task per draft.
    expect(await openSeedTasks(page)).toMatch(EITHER_ANSWER);
    expect(await openSeedTasks(page)).toMatch(EITHER_ANSWER);
    // The first rule's draft is one no spec moves (D-042): it has exactly one task waiting.
    const draft = await latestVersion(0);
    const task = await undecidedTaskOf(draft.rule_version_id);
    if (task === null) throw new Error(`the draft of ${draft.rule_key} has a task waiting`);
    const waiting = (await taskDetail(task.task_id)).tasks.filter(
      (each) => each.status !== "decided",
    );
    expect(waiting.map((each) => each.task_id)).toEqual([task.task_id]);
    await checkA11y();
  });

  test("lists the open tasks in the rulebook's order, each with its version and claim", async ({
    page,
    checkA11y,
  }) => {
    await openSeedTasks(page);
    await page.goto("/admin/review");
    const expected = await expectQueueShown(page, "status=open&limit=25");
    const first = expected[0];
    if (first === undefined) throw new Error("the queue holds an open task");
    const row = page.locator(`tr[data-task='${first.task_id}']`);
    await expect(row.getByRole("link", { name: first.title })).toHaveAttribute(
      "href",
      `/admin/review/${first.task_id}`,
    );
    await expect(row).toContainText(`${first.rule_key} v${first.version}`);
    await expect(row).toContainText(`${first.approvals} of ${first.required_approvals} approvals`);
    await expect(row).toContainText("Not claimed");
    await expect(row.getByRole("button", { name: `Claim: ${first.title}` })).toBeVisible();
    await expect(page.locator("[data-slot='review-sampling']")).toHaveCount(0);
    await checkA11y();
  });

  test("filters by status, kind and regulator, each a chip in the address", async ({
    page,
    checkA11y,
  }) => {
    await openSeedTasks(page);
    const stats = await reviewStats();
    const regulator = stats.by_regulator[0]?.regulator;
    if (regulator === undefined) throw new Error("the stats count a regulator once a task exists");
    await page.goto("/admin/review");

    const statusChips = page.getByRole("navigation", { name: "Show tasks by status" });
    await statusChips.getByRole("link", { name: "Every status" }).click();
    await expect(page).toHaveURL(/\/admin\/review\?status=all$/);
    await expect(statusChips.getByRole("link", { name: "Every status" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expectQueueShown(page, "limit=25");

    const kinds = page.getByRole("navigation", { name: "Show tasks by kind" });
    await kinds.getByRole("link", { name: "Seed draft" }).click();
    await expect(page).toHaveURL(/\/admin\/review\?status=all&kind=seed$/);
    const seeds = await expectQueueShown(page, "kind=seed&limit=25");
    expect(seeds.map((task) => task.kind)).toEqual(seeds.map(() => "seed"));
    const seedRows = page.locator("[data-slot='queue-table'] tbody tr");
    expect(
      await seedRows.evaluateAll((elements) =>
        elements.map((row) => row.getAttribute("data-kind")),
      ),
    ).toEqual(seeds.map(() => "seed"));

    const regulators = page.getByRole("navigation", { name: "Show tasks by regulator" });
    await regulators.getByRole("link", { name: regulator, exact: true }).click();
    await expect(page).toHaveURL(
      new RegExp(`/admin/review\\?status=all&kind=seed&regulator=${regulator}$`),
    );
    await expectQueueShown(page, `kind=seed&regulator=${regulator}&limit=25`);

    await kinds.getByRole("link", { name: "Rule candidate" }).click();
    await expect(page).toHaveURL(/kind=candidate/);
    const candidates = await expectQueueShown(
      page,
      `kind=candidate&regulator=${regulator}&limit=25`,
    );
    if (candidates.length === 0) {
      await expect(
        page.getByRole("heading", { name: "No task matches these filters" }),
      ).toBeVisible();
    }
    await checkA11y();
  });

  test("the strip counts the queue as the rulebook does and links the stats", async ({
    page,
    checkA11y,
  }) => {
    await openSeedTasks(page);
    // Other specs open tasks meanwhile: the page is compared with the stats read either side of
    // it, and read again when they differ.
    let shown: StatsBody | null = null;
    for (let attempt = 0; attempt < 3 && shown === null; attempt += 1) {
      const before = await reviewStats();
      await page.goto("/admin/review");
      const after = await reviewStats();
      if (JSON.stringify(before.by_status) === JSON.stringify(after.by_status)) shown = after;
    }
    if (shown === null) throw new Error("the queue kept changing while the page rendered");
    const cards = page.locator("[data-slot='review-strip-cards']");
    await expect(cards).toContainText(`Open${shown.by_status.open}`);
    await expect(cards).toContainText(`Claimed${shown.by_status.claimed}`);
    await expect(cards).toContainText(`Decided${shown.by_status.decided}`);
    await expect(cards).toContainText(
      shown.candidates.acceptance_rate === null ? "None decided yet" : "%",
    );
    await page
      .locator("[data-slot='review-strip']")
      .getByRole("link", { name: "Review stats" })
      .click();
    await expect(page).toHaveURL(/\/admin\/review\/stats$/);
    // The stats page's title streams in after its URL: axe reads the page once it is there.
    await expect(page.getByRole("heading", { level: 1, name: "Review stats" })).toBeVisible();
    await expect(page).toHaveTitle(/Review stats/);
    await checkA11y();
  });

  test("moves through the tasks with j and k, lists the keys with ?, and opens one with Enter", async ({
    page,
    checkA11y,
  }) => {
    await openSeedTasks(page);
    await page.goto("/admin/review?status=all");
    await waitForHydration(page, "[data-slot='task-link']");
    const links = page.locator("[data-slot='task-link']");
    expect(await links.count()).toBeGreaterThan(2);
    await expect(links.nth(0)).toHaveAttribute("tabindex", "0");
    await expect(links.nth(1)).toHaveAttribute("tabindex", "-1");

    // Outside the list the keys are the page's: nothing moves and no dialog opens.
    await page.keyboard.press("j");
    await expect(links.nth(0)).not.toBeFocused();
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await links.nth(0).focus();
    await page.keyboard.press("?");
    const dialog = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Move to the next task");
    await expect(dialog).toContainText("No key claims a task");
    await checkA11y();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(links.nth(0)).toBeFocused();

    // A key held down moves one task, not one per repeat.
    await page.keyboard.down("j");
    await page.keyboard.down("j");
    await page.keyboard.down("j");
    await page.keyboard.up("j");
    await expect(links.nth(1)).toBeFocused();
    await expect(links.nth(1)).toHaveAttribute("tabindex", "0");
    await expect(links.nth(0)).toHaveAttribute("tabindex", "-1");
    await page.keyboard.press("k");
    await expect(links.nth(0)).toBeFocused();
    const href = await links.nth(0).getAttribute("href");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`${href}$`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("leaves the keys to a dialog", async ({ page }) => {
    await openSeedTasks(page);
    await page.goto("/admin/review?status=all");
    await waitForHydration(page, "[data-slot='task-link']");
    // With the shortcuts dialog open, j is the dialog's and moves nothing in the list.
    const links = page.locator("[data-slot='task-link']");
    await links.nth(0).focus();
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
    await page.keyboard.press("j");
    await expect(links.nth(1)).not.toBeFocused();
  });
});

/** The queue as a reviewer sees it: what review sampling waits for. */
test.describe("the review queue for a reviewer", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test("says what review sampling waits for", async ({ page, signIn }) => {
    await signIn(REVIEWER);
    await page.goto("/admin/review");
    await expect(page.locator("[data-slot='review-sampling']")).toContainText(
      "Review sampling is not built yet: it waits for POST /v1/rulebook/review/samples",
    );
  });
});
