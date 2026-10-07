import { ANALYST, IS_CI, expect, seededTenantId, test } from "./fixtures";
import { openSeedTasks, reviewStats, type StatsBody } from "./review-helpers";

/** The counts the page shows, without the oldest task's age, which grows by the second. */
function counts(stats: StatsBody): string {
  return JSON.stringify([stats.by_status, stats.by_regulator, stats.decisions, stats.candidates]);
}

/**
 * The review stats against the stack's rulebook: every number on the page is the rulebook's
 * `GET /v1/rulebook/review/stats`, read either side of the page so a task another spec opens
 * meanwhile reads the page again rather than failing it.
 */
test.describe("the review stats", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test("shows the counts by status and regulator, the decisions and the candidates", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await openSeedTasks(page);
    let shown: StatsBody | null = null;
    for (let attempt = 0; attempt < 3 && shown === null; attempt += 1) {
      const before = await reviewStats();
      await page.goto("/admin/review/stats");
      const after = await reviewStats();
      if (counts(before) === counts(after)) shown = after;
    }
    if (shown === null) throw new Error("the queue kept changing while the page rendered");
    await expect(page.getByRole("heading", { level: 1, name: "Review stats" })).toBeVisible();
    const status = page.locator("[data-slot='stats-status']");
    const { open, claimed, decided } = shown.by_status;
    await expect(status).toContainText(`Open${open}`);
    await expect(status).toContainText(`Claimed${claimed}`);
    await expect(status).toContainText(`Decided${decided}`);
    await expect(status).toContainText(`Total${open + claimed + decided}`);

    const regulators = page.locator("[data-slot='stats-regulators'] tbody tr");
    await expect(regulators).toHaveCount(shown.by_regulator.length);
    for (const row of shown.by_regulator) {
      await expect(page.locator(`tr[data-regulator='${row.regulator}']`)).toContainText(
        `${row.regulator}${row.open}${row.claimed}${row.decided}${row.open + row.claimed + row.decided}`,
      );
    }

    const decisions = page.locator("[data-slot='stats-decisions']");
    await expect(decisions).toContainText(`Approved${shown.decisions.approved}`);
    await expect(decisions).toContainText(`Returned${shown.decisions.returned}`);
    await expect(decisions).toContainText(`Rejected${shown.decisions.rejected}`);

    const candidates = page.locator("[data-slot='stats-candidates']");
    await expect(candidates).toContainText(`Decided${shown.candidates.decided}`);
    await expect(candidates).toContainText(
      `Approved without edits${shown.candidates.approved_without_edits}`,
    );
    const acceptance = page.locator("[data-slot='stats-acceptance']");
    if (shown.candidates.acceptance_rate === null) {
      await expect(acceptance).toContainText("Acceptance rate: None decided yet");
      await expect(acceptance).toContainText("No candidate is decided yet.");
    } else {
      await expect(acceptance).toContainText(
        `Acceptance rate: ${Math.round(shown.candidates.acceptance_rate * 100)}%`,
      );
    }
    const time = page.locator("[data-slot='stats-time']");
    await expect(time).toContainText(
      shown.median_seconds_to_decide === null ? "No task decided yet" : "Median time to decide",
    );
    await expect(time).toContainText(shown.oldest_open_at === null ? "No task waits" : "opened");
    await checkA11y();
    await page.getByRole("link", { name: "Back to the review queue" }).click();
    await expect(page).toHaveURL(/\/admin\/review$/);
  });
});
