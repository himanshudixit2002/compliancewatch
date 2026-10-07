import type { Page } from "@playwright/test";
import { expect, waitForHydration } from "./fixtures";
import { rulebookGet } from "./rulebook-helpers";

/**
 * Reads of the rulebook's review queue the review specs compare the pages with, straight from the
 * stack's rulebook. The specs never claim, edit or decide a task: on `make web-stack` every task is
 * a seed task over one of the seed calendar's own drafts (the rulebook has no route that stages a
 * version of a spec's own, and rule candidates arrive only through the worker's intake, which the
 * stack does not run), so those steps are covered by the unit tests over recorded shapes (D-063).
 * The one write is "Open seed tasks", pressed through the page: it opens a task for each seed draft
 * that has none and is idempotent, so a run and a rerun see the same queue.
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

export interface TaskDetailBody {
  task: QueuedTaskRow;
  rule_version: {
    rule_version_id: string;
    rule_key: string;
    version: number;
    title: string;
    status: string;
  } | null;
  citations: { citation_id: string; clause_ref: string; quote: string; document_id: string }[];
  tasks: { task_id: string }[];
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
