import type { Page } from "@playwright/test";
import { expect, waitForHydration } from "./fixtures";
import { rulebookGet } from "./rulebook-helpers";

/**
 * Reads of the rulebook's review queue the review specs compare the pages with, straight from the
 * stack's rulebook. On `make web-stack` every task is a seed task over one of the seed calendar's
 * own drafts (the rulebook has no route that stages a version of a spec's own, and rule
 * candidates arrive only through the worker's intake, which the stack does not run). The specs
 * that claim, edit and decide take the drafts of rules no other spec moves, each by its position
 * in key order, through the pages (D-063); "Open seed tasks" opens a task for each seed draft that
 * has none and is idempotent. Since those specs run beside the reading ones, a page is compared
 * with the queue read either side of it (`expectQueueShown`), not with a count taken once.
 */
export interface QueuedTaskRow {
  task_id: string;
  rule_version_id: string | null;
  kind: string;
  status: string;
  regulator: string;
  title: string;
  rule_key: string | null;
  version: number | null;
  version_status: string | null;
  high_impact: boolean;
  claimed_by: string | null;
  approvals: number;
  required_approvals: number;
}

export interface StatsBody {
  by_status: { open: number; claimed: number; decided: number };
  by_regulator: { regulator: string; open: number; claimed: number; decided: number }[];
  decisions: { approved: number; returned: number; rejected: number };
  median_seconds_to_decide: number | null;
  oldest_open_at: string | null;
  candidates: {
    decided: number;
    approved: number;
    approved_without_edits: number;
    rejected: number;
    acceptance_rate: number | null;
  };
}

export interface TaskRow {
  task_id: string;
  rule_version_id: string | null;
  status: string;
  claimed_by: string | null;
  decision: string | null;
  decided_by: string | null;
}

export interface TaskDetailBody {
  task: TaskRow;
  rule_version: {
    rule_version_id: string;
    rule_key: string;
    version: number;
    title: string;
    status: string;
    high_impact: boolean;
    specification: Record<string, unknown>;
  } | null;
  citations: { citation_id: string; clause_ref: string; quote: string; document_id: string }[];
  tasks: TaskRow[];
  approved_by: string[];
  required_approvals: number;
}

export async function queuePage(query: string): Promise<QueuedTaskRow[]> {
  return (await rulebookGet<{ items: QueuedTaskRow[] }>(`/v1/rulebook/review/tasks?${query}`))
    .items;
}

export async function reviewStats(): Promise<StatsBody> {
  return rulebookGet<StatsBody>("/v1/rulebook/review/stats");
}

export async function taskDetail(taskId: string): Promise<TaskDetailBody> {
  return rulebookGet<TaskDetailBody>(`/v1/rulebook/review/tasks/${taskId}`);
}

/**
 * The task of a version that waits for a decision (open, or claimed), from one read of the
 * waiting seed tasks per status; null when it has none (its last one was rejected and no one has
 * pressed "Open seed tasks" since).
 */
export async function undecidedTaskOf(ruleVersionId: string): Promise<QueuedTaskRow | null> {
  for (const status of ["open", "claimed"]) {
    const found = (await queuePage(`status=${status}&kind=seed&limit=200`)).find(
      (task) => task.rule_version_id === ruleVersionId,
    );
    if (found !== undefined) return found;
  }
  return null;
}

/**
 * Checks that the page shows the queue the rulebook answers for the query, row for row and in its
 * order. Other specs claim, decide and open tasks meanwhile, so the queue is read either side of
 * the page and the page read again (up to three times) until the two reads and the page agree.
 * Returns the queue the page showed.
 */
export async function expectQueueShown(page: Page, query: string): Promise<QueuedTaskRow[]> {
  const rows = page.locator("[data-slot='queue-table'] tbody tr");
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const before = await queuePage(query);
    if (attempt > 0) await page.reload();
    const shown = await rows.evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("data-task")),
    );
    const after = await queuePage(query);
    const ids = (tasks: QueuedTaskRow[]) => tasks.map((task) => task.task_id);
    if (
      JSON.stringify(ids(before)) === JSON.stringify(ids(after)) &&
      JSON.stringify(shown) === JSON.stringify(ids(after))
    ) {
      return after;
    }
  }
  throw new Error(`the queue (${query}) kept changing while the page rendered`);
}

/**
 * Presses "Open seed tasks" on the queue and waits for its answer, which says how many it opened
 * or that every seed draft already has a task. Returns the answer's text.
 */
export async function openSeedTasks(page: Page): Promise<string> {
  await page.goto("/admin/review");
  const button = page.getByRole("button", { name: "Open seed tasks" });
  await expect(button).toBeEnabled();
  await waitForHydration(page, "[data-slot='seed-tasks'] button");
  await button.click();
  const outcome = page.locator("[data-slot='seed-tasks-outcome'] [data-slot='write-result']");
  await expect(outcome).toBeVisible();
  return (await outcome.textContent()) ?? "";
}
