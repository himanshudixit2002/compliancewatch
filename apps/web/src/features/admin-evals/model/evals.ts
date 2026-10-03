import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The evals screen: the evaluation runs that scored a model against the golden sets.
 * `GET /v1/eval/runs` has no committed spec yet, so these are plain types; instants are ISO
 * strings and the view formats them in IST.
 */

/** Running until it finishes; passed when it met every gate, failed when it missed one. */
export type EvalRunStatus = "running" | "passed" | "failed";

export const EVAL_RUN_STATUSES: readonly EvalRunStatus[] = ["running", "passed", "failed"];

/** One evaluation run. */
export interface EvalRun {
  id: string;
  /** What was run, such as "Extraction, nightly". */
  name: string;
  /** The model it scored, as the gateway names it. */
  model: string;
  status: EvalRunStatus;
  /** The headline score from 0 to 1; null while the run has none. */
  score: number | null;
  /** When it started. */
  startedAt: string;
}

/** The figures in the summary row. */
export interface EvalSummary {
  total: number;
  passed: number;
  failed: number;
  /** How many runs have a score. */
  scored: number;
  /** The mean score of those runs as a whole percentage; null when none has a score. */
  averageScore: number | null;
}

const STATUS_LABEL: Readonly<Record<EvalRunStatus, MessageKey>> = {
  running: "adminEvals.status.running",
  passed: "adminEvals.status.passed",
  failed: "adminEvals.status.failed",
};

const STATUS_TONE: Readonly<Record<EvalRunStatus, Tone>> = {
  running: "info",
  passed: "success",
  failed: "danger",
};

export function runStatusLabel(status: EvalRunStatus): string {
  return t(STATUS_LABEL[status]);
}

export function runStatusTone(status: EvalRunStatus): Tone {
  return STATUS_TONE[status];
}

/** A score from 0 to 1 as a whole percentage; a missing score stays missing. */
export function scorePercent(score: number | null): number | null {
  return score === null ? null : Math.round(score * 100);
}

/** The newest run first. */
export function sortRuns(runs: readonly EvalRun[]): EvalRun[] {
  return [...runs].sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt));
}

export function evalSummary(runs: readonly EvalRun[]): EvalSummary {
  const scores = runs.flatMap((run) => (run.score === null ? [] : [run.score]));
  const sum = scores.reduce((total, score) => total + score, 0);
  return {
    total: runs.length,
    passed: runs.filter((run) => run.status === "passed").length,
    failed: runs.filter((run) => run.status === "failed").length,
    scored: scores.length,
    averageScore: scorePercent(scores.length === 0 ? null : sum / scores.length),
  };
}
