import { randomUUID } from "node:crypto";
import {
  ANALYST,
  IS_CI,
  REVIEWER,
  expect,
  seededTenantId,
  test,
  waitForHydration,
} from "./fixtures";
import { openSeedTasks, queuePage, taskDetail, type QueuedTaskRow } from "./review-helpers";
import { ruleKeys } from "./rulebook-helpers";

/**
 * The review workbench against the stack's rulebook. Every task there reviews one of the seed
 * calendar's own drafts, which no spec claims, edits or decides (D-063): this spec opens a seed
 * task's workbench read-only and checks what it shows against the rulebook's task read, the steps
 * each role is offered (without taking any), and the not-found page. Claiming, drafting from a
 * candidate, editing with the predicate editor, the two approvals, the return, the rejection and
 * the diff of a drafted candidate are covered by the unit and component tests over the rulebook's
 * recorded shapes.
 */
/**
 * An open seed task over the last rule in key order: the other specs move the drafts at the first
 * positions (rulebook-helpers' latestVersion), so this one's draft stays as the seed wrote it.
 */
async function aQuietSeedTask(): Promise<QueuedTaskRow> {
  const key = (await ruleKeys()).at(-1);
  const open = await queuePage("status=open&kind=seed&limit=200");
  const task = open.find((candidate) => candidate.rule_key === key);
  if (task === undefined) throw new Error(`the seed task of ${String(key)} is open`);
  return task;
}

test.describe("the review workbench", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test("shows a seed task's draft, its claim and its history, read-only for an analyst's approval", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await openSeedTasks(page);
    const task = await aQuietSeedTask();
    const detail = await taskDetail(task.task_id);
    const version = detail.rule_version;
    if (version === null) throw new Error("a seed task reviews a version");

    await page.goto(`/admin/review/${task.task_id}`);
    await expect(page.getByRole("heading", { level: 1, name: version.title })).toBeVisible();
    const facts = page.locator("[data-slot='task-facts']");
    await expect(facts).toContainText("Seed draft");
    await expect(facts).toContainText("Open");
    await expect(facts).toContainText(task.regulator);
    await expect(
      facts.getByRole("link", { name: `${version.rule_key} v${version.version}` }),
    ).toHaveAttribute("href", `/admin/rulebook/versions/${version.rule_version_id}`);

    const source = page.locator("[data-slot='source-pane']");
    if (detail.citations.length === 0) {
      await expect(source.locator("[data-slot='source-empty']")).toBeVisible();
      await expect(source).toContainText("The draft cites no clause yet.");
    } else {
      await expect(source.locator("[data-slot='source-document']")).not.toHaveCount(0);
      await expect(source.locator("[data-citation]")).toHaveCount(detail.citations.length);
    }

    const rule = page.locator("[data-slot='rule-pane']");
    await expect(rule.locator("[data-slot='draft-content']")).toContainText(
      `${version.rule_key} v${version.version}`,
    );
    await expect(rule.locator("[data-slot='specification']").first()).toBeVisible();
    await expect(rule.getByRole("button", { name: "Claim this task" })).toBeVisible();
    await expect(rule.locator("[data-slot='edit-blocked']")).toContainText(
      "Claim the task to edit its draft",
    );
    await expect(rule.locator("[data-slot='approve-blocked']")).toContainText(
      "Approving is a reviewer's or an admin's",
    );
    await expect(rule.getByRole("button", { name: "Return" })).toBeDisabled();
    await expect(rule.getByRole("button", { name: "Reject" })).toBeDisabled();
    await expect(rule.locator("[data-slot='approvals']")).toContainText(
      `${detail.approved_by.length} of ${detail.required_approvals} approvals in this round.`,
    );

    await expect(page.locator("[data-slot='diff-no-previous']")).toContainText(
      "The rule has no earlier version to compare with.",
    );
    const history = page.locator("[data-slot='history-tasks']");
    await expect(history.locator("tbody tr")).toHaveCount(detail.tasks.length);
    await expect(history.locator(`tr[data-task='${task.task_id}']`)).toContainText("This task");
    await checkA11y();
  });

  test("offers a reviewer the approval with the high-impact tag", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(REVIEWER);
    await openSeedTasks(page);
    const task = await aQuietSeedTask();
    await page.goto(`/admin/review/${task.task_id}`);
    await waitForHydration(page, "[data-decision='approve'] button");
    const approve = page.locator("[data-decision='approve']");
    await expect(approve.getByRole("checkbox", { name: /Mark it high impact/ })).toBeVisible();
    await expect(approve.getByRole("button", { name: "Approve" })).toBeEnabled();
    // The dialog says what the rulebook records; the spec cancels it: the draft is the seed's.
    await approve.getByRole("button", { name: "Approve" }).click();
    const dialog = page.getByRole("dialog", { name: "Approve this version?" });
    await expect(dialog).toContainText("records your approval with your user id");
    await checkA11y();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    const now = await taskDetail(task.task_id);
    expect(now.task.status).toBe("open");
  });

  test("opens the original file of a cited document in a new tab, or says the pipeline holds none", async ({
    page,
    signIn,
  }) => {
    await signIn(ANALYST);
    await openSeedTasks(page);
    const open = await queuePage("status=open&kind=seed&limit=200");
    let cited: QueuedTaskRow | undefined;
    for (const task of open) {
      if ((await taskDetail(task.task_id)).citations.length > 0) {
        cited = task;
        break;
      }
    }
    test.skip(cited === undefined, "no seed draft cites a document on this stack yet");
    if (cited === undefined) return;
    await page.goto(`/admin/review/${cited.task_id}`);
    const document = page.locator("[data-slot='source-document']").first();
    const file = document.locator("[data-slot='original-file']");
    if ((await file.count()) > 0) {
      await expect(file).toHaveAttribute("target", "_blank");
      await expect(file).toHaveAttribute("rel", "noopener");
      await expect(file).toHaveAttribute("href", /\/api-bff\/pipeline\/documents\/.+\/raw$/);
    } else {
      await expect(document.locator("[data-slot='original-file-none']")).toBeVisible();
    }
    await expect(document.locator("li[data-cited]").first()).toBeVisible();
    await expect(page.locator("iframe, embed, object")).toHaveCount(0);
  });

  test("an id the rulebook does not hold is the not-found page", async ({ page, signIn }) => {
    await signIn(ANALYST);
    await page.goto(`/admin/review/${randomUUID()}`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });
});
