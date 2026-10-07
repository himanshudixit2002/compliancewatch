import type { Page } from "@playwright/test";
import {
  ANALYST,
  IS_CI,
  REVIEWER,
  expect,
  seededTenantId,
  test,
  waitForHydration,
} from "./fixtures";
import { holdingPosition } from "./position-lock";
import {
  openSeedTasks,
  taskDetail,
  undecidedTaskOf,
  type QueuedTaskRow,
  type TaskDetailBody,
} from "./review-helpers";
import {
  conditionAttributes,
  latestVersion,
  versionNow,
  type VersionRow,
} from "./rulebook-helpers";

/**
 * The review workbench's writes against the rulebook `make web-stack` starts with the seed
 * calendar's drafts (D-063). As the publish specs do (D-042), each test owns the draft of a rule
 * no other spec moves, by its position in key order, held while it works so two copies of a test
 * never move it at once, and first returns the draft's task when an earlier run left it claimed,
 * in review or with an approval. No test ever completes an approval round: a completed round marks
 * the seed draft reviewed, which the memory store could not undo, so the one approval is always
 * of a version tagged high impact, which needs two different reviewers, and the test returns the
 * version to draft afterwards, which opens its next task for the next run. The rejected draft gets
 * its next task from "Open seed tasks". Every analyst and reviewer is a synthetic user of the fake
 * sign-in.
 */
const STEPS_POSITION = 8;
const REJECT_POSITION = 9;
/** Room for a copy of the test that holds the position first. */
const HOLDING_TIMEOUT = 180_000;
/** The attribute the edit adds to the condition: a registration's yes-or-no fact. */
const ADDED = "makes_inter_state_supplies";

function workbench(taskId: string): string {
  return `/admin/review/${taskId}`;
}

/** The task waiting for a decision on the draft at a position, opening the seed tasks if none. */
async function waitingTask(
  page: Page,
  position: number,
): Promise<{ version: VersionRow; task: QueuedTaskRow }> {
  const version = await latestVersion(position);
  let task = await undecidedTaskOf(version.rule_version_id);
  if (task === null) {
    await openSeedTasks(page);
    task = await undecidedTaskOf(version.rule_version_id);
  }
  if (task === null) throw new Error(`the draft of ${version.rule_key} has a task waiting`);
  return { version, task };
}

/** A round no one has started: the task open, the version a draft without approvals. */
function fresh(detail: TaskDetailBody): boolean {
  return (
    detail.task.status === "open" &&
    detail.task.claimed_by === null &&
    detail.rule_version?.status === "draft" &&
    detail.approved_by.length === 0
  );
}

/** Returns a task through the workbench with a note; the next task opens and is returned. */
async function returnTask(page: Page, taskId: string): Promise<string> {
  await page.goto(workbench(taskId));
  const decide = page.locator("[data-slot='decide-panel']");
  await waitForHydration(page, "[data-decision='return'] textarea");
  await decide
    .locator("[data-decision='return'] textarea")
    .fill("Example reason: start the e2e run from a fresh round");
  await decide.getByRole("button", { name: "Return", exact: true }).click();
  await page
    .getByRole("dialog", { name: "Return the version for rework?" })
    .getByRole("button", { name: "Return", exact: true })
    .click();
  const outcome = page.locator("[data-slot='decide-outcome']");
  await expect(outcome).toContainText("Returned to draft: the rework has a new task.");
  const next = await outcome
    .getByRole("link", { name: "Open the rework's task" })
    .getAttribute("href");
  const nextId = next?.split("/").at(-1);
  if (nextId === undefined || nextId === "") throw new Error("a return opens the next task");
  return nextId;
}

/** The draft's waiting task in a fresh round, returning what an earlier run left mid-way. */
async function freshTask(
  page: Page,
  position: number,
): Promise<{ version: VersionRow; task: QueuedTaskRow }> {
  const found = await waitingTask(page, position);
  if (fresh(await taskDetail(found.task.task_id))) return found;
  const nextId = await returnTask(page, found.task.task_id);
  const next = await taskDetail(nextId);
  expect(fresh(next), "the returned draft's next task starts a fresh round").toBe(true);
  return {
    version: await versionNow(found.version.rule_version_id),
    task: { ...found.task, ...next.task },
  };
}

test.describe("the review workbench's steps", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test("claims from the queue, edits the condition, takes one high-impact approval, is refused a second, and returns", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.setTimeout(HOLDING_TIMEOUT);
    await holdingPosition(STEPS_POSITION, async () => {
      await signIn(ANALYST);
      const { version, task } = await freshTask(page, STEPS_POSITION);

      // Claim: the queue row's button, as the analyst.
      await page.goto("/admin/review?kind=seed");
      const row = page.locator(`tr[data-task='${task.task_id}']`);
      await waitForHydration(page, `tr[data-task='${task.task_id}'] button`);
      await row.getByRole("button", { name: `Claim: ${version.title}` }).click();
      await expect(page.locator("[data-slot='queue-claim-outcome']")).toContainText(
        "The task is yours",
      );
      expect((await taskDetail(task.task_id)).task.status).toBe("claimed");
      // The claimed tasks list it, marked as the analyst's own.
      await page.goto("/admin/review?status=claimed&kind=seed");
      const mine = page.locator(`tr[data-task='${task.task_id}']`);
      await expect(mine).toHaveAttribute("data-mine", "true");
      await expect(mine).toContainText("Yours");

      // The workbench: the claim is the analyst's, who is not offered the approval.
      await page.goto(workbench(task.task_id));
      const rule = page.locator("[data-slot='rule-pane']");
      await expect(rule.locator("[data-slot='claim-panel']")).toHaveAttribute("data-claim", "mine");
      await expect(rule.locator("[data-slot='approve-blocked']")).toContainText(
        "Approving is a reviewer's or an admin's",
      );
      await expect(
        rule.locator("[data-decision='approve']").getByRole("button", { name: "Approve" }),
      ).toHaveCount(0);

      // Edit: the condition gains a predicate picked through the attribute's suggestions. The one
      // an earlier run added is removed first, so the condition stays one predicate longer, and
      // the new one says the other value, so every run changes the condition.
      const editor = rule.locator("[data-slot='edit-panel'] [data-slot='predicate-editor']");
      await waitForHydration(
        page,
        "[data-slot='edit-panel'] [data-slot='predicate-editor'] button",
      );
      const items = (version.specification.all_of as Record<string, unknown>[] | undefined) ?? [];
      const earlier = items.findIndex((item) => conditionAttributes(item).includes(ADDED));
      const value = items[earlier]?.value === true ? "false" : "true";
      let parts = items.length;
      if (earlier >= 0) {
        await editor.getByRole("button", { name: `Remove part 1.${earlier + 1}` }).click();
        parts -= 1;
      }
      await editor.getByRole("button", { name: "Add a condition to Group 1" }).click();
      const added = editor.getByRole("group", { name: `Condition 1.${parts + 1}` });
      const attribute = added.getByRole("combobox", { name: /Attribute/ });
      await attribute.fill("makes_inter");
      await page.getByRole("option", { name: new RegExp(ADDED) }).click();
      await expect(attribute).toHaveValue(ADDED);
      await added.getByLabel(/^Comparison/).selectOption("eq");
      await added.getByLabel(/^Value/).selectOption(value);
      await expect(editor.locator("[data-slot='predicate-preview']")).toContainText(
        value === "true" ? "Yes" : "No",
      );
      await rule
        .locator("[data-slot='edit-panel']")
        .getByLabel(/^Why \(for the audit\)/)
        .fill("Example reason: the duty applies to inter-state suppliers only");
      await checkA11y();
      await rule.getByRole("button", { name: "Save the draft" }).click();
      const edited = rule.locator("[data-slot='edit-outcome']");
      await expect(edited).toContainText("The draft is saved.");
      await expect(edited).toContainText("Changed: Condition.");
      const saved = await versionNow(version.rule_version_id);
      const now = (
        (saved.specification.all_of as Record<string, unknown>[] | undefined) ?? []
      ).filter((item) => conditionAttributes(item).includes(ADDED));
      expect(now).toEqual([{ attribute: ADDED, operator: "eq", value: value === "true" }]);
      expect(saved.status).toBe("draft");

      // Approve as a reviewer, tagging the version high impact: one approval of two.
      await signIn(REVIEWER);
      await page.reload();
      const approve = page.locator("[data-decision='approve']");
      await waitForHydration(page, "[data-decision='approve'] button");
      const tag = approve.getByRole("checkbox", { name: /Mark it high impact/ });
      if (!(await tag.isDisabled())) await tag.check();
      await expect(tag).toBeChecked();
      await approve.getByRole("button", { name: "Approve" }).click();
      const confirm = page.getByRole("dialog", { name: "Approve this version?" });
      // Never complete a round: the dialog must say a second reviewer is still needed.
      await expect(confirm).toContainText("A second, different reviewer must approve");
      await checkA11y();
      await confirm.getByRole("button", { name: "Approve" }).click();
      const outcome = page.locator("[data-slot='decide-outcome']");
      await expect(outcome).toContainText("Your approval is recorded: 1 of 2 approvals.");
      await expect(outcome).toContainText("A second, different reviewer completes the round.");
      await expect(outcome).toContainText("Version: In review.");
      const approved = await taskDetail(task.task_id);
      expect(approved.task.status).toBe("open");
      expect(approved.rule_version).toMatchObject({ status: "in_review", high_impact: true });
      expect(approved.approved_by).toHaveLength(1);
      await expect(page.locator("[data-slot='approvals']")).toContainText(
        "1 of 2 approvals in this round.",
      );

      // The same reviewer again: the rulebook's refusal, said plainly.
      await approve.getByRole("button", { name: "Approve" }).click();
      await page
        .getByRole("dialog", { name: "Approve this version?" })
        .getByRole("button", { name: "Approve" })
        .click();
      await expect(outcome).toContainText("A different reviewer must approve");
      await expect(outcome.locator("[data-slot='correlation-id']")).toBeVisible();
      expect((await taskDetail(task.task_id)).approved_by).toHaveLength(1);
      await checkA11y();

      // Return: the version goes back to draft and its next task opens.
      const nextId = await returnTask(page, task.task_id);
      await expect(page.locator("[data-slot='decide-outcome']")).toContainText("Version: Draft.");
      const returned = await taskDetail(task.task_id);
      expect(returned.task).toMatchObject({ status: "decided", decision: "return" });
      expect((await versionNow(version.rule_version_id)).status).toBe("draft");
      expect((await undecidedTaskOf(version.rule_version_id))?.task_id).toBe(nextId);
      await page
        .locator("[data-slot='decide-outcome']")
        .getByRole("link", { name: "Open the rework's task" })
        .click();
      await expect(page).toHaveURL(new RegExp(`${workbench(nextId)}$`));
      await expect(page.locator("[data-slot='task-facts']")).toContainText("Open");
    });
  });

  test("rejects a seed task with a note: the draft stays a draft, and opening the seed tasks gives it a new one", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.setTimeout(HOLDING_TIMEOUT);
    await holdingPosition(REJECT_POSITION, async () => {
      await signIn(ANALYST);
      const { version, task } = await waitingTask(page, REJECT_POSITION);
      await page.goto(workbench(task.task_id));
      const decide = page.locator("[data-slot='decide-panel']");
      // An analyst returns and rejects; the approval is a reviewer's.
      await expect(decide.locator("[data-slot='approve-blocked']")).toContainText(
        "Approving is a reviewer's or an admin's",
      );
      await expect(decide.getByRole("button", { name: "Approve" })).toHaveCount(0);
      await waitForHydration(page, "[data-decision='reject'] textarea");
      const reject = decide.locator("[data-decision='reject']");
      await expect(reject.getByRole("button", { name: "Reject" })).toBeDisabled();
      await reject.locator("textarea").fill("Example reason: the seed draft is out of scope here");
      await reject.getByRole("button", { name: "Reject" }).click();
      const dialog = page.getByRole("dialog", { name: "Reject this task?" });
      await expect(dialog).toContainText("The version stays a draft.");
      await checkA11y();
      await dialog.getByRole("button", { name: "Reject" }).click();
      const outcome = page.locator("[data-slot='decide-outcome']");
      await expect(outcome).toContainText("Rejected: the task is closed.");
      await expect(outcome).toContainText("Version: Draft.");
      await expect(page.locator("[data-slot='decide-closed']")).toBeVisible();
      expect((await taskDetail(task.task_id)).task).toMatchObject({
        status: "decided",
        decision: "reject",
      });
      expect((await versionNow(version.rule_version_id)).status).toBe("draft");
      expect(await undecidedTaskOf(version.rule_version_id)).toBeNull();
      await checkA11y();

      // The rejected seed draft gets its next task when the seed tasks are opened.
      await openSeedTasks(page);
      const next = await undecidedTaskOf(version.rule_version_id);
      expect(next?.task_id).not.toBe(task.task_id);
      expect(next?.status).toBe("open");
    });
  });
});
