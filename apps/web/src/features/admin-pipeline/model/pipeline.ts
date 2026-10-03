import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The pipeline screen's model: the runs that fetch, parse and extract regulator documents, as
 * `GET /v1/pipeline/runs` will return them (WP19; no committed spec yet), with how far each has
 * got and why a failed one stopped.
 */
export type PipelineRunStatus = "pending" | "running" | "completed" | "failed";

/** The statuses in the order the tabs show them, the runs that need watching first. */
export const PIPELINE_RUN_STATUSES: readonly PipelineRunStatus[] = [
  "running",
  "failed",
  "pending",
  "completed",
];

export interface PipelineRun {
  id: string;
  /** What the run works through, for example "CBIC circulars". */
  name: string;
  /** The pipeline stage: fetch, parse, extract and so on. */
  stage: string;
  status: PipelineRunStatus;
  /** Documents handled so far. */
  processed: number;
  /** Documents the run will handle; null until it has counted them. */
  total: number | null;
  /** When it started, an ISO instant; null until it has. */
  startedAt: string | null;
  /** When it completed or failed, an ISO instant; null until it has. */
  finishedAt: string | null;
  /** Why it failed; null unless it failed. */
  error: string | null;
}

/** The form field that carries a run's id to the retry action. */
export const RUN_ID_FIELD = "runId";

/** How many runs there are in all and in each status. */
export type PipelineCounts = Readonly<Record<PipelineRunStatus | "total", number>>;

const STATUS_LABEL: Readonly<Record<PipelineRunStatus, MessageKey>> = {
  pending: "adminPipeline.status.pending",
  running: "adminPipeline.status.running",
  completed: "adminPipeline.status.completed",
  failed: "adminPipeline.status.failed",
};

const STATUS_TONE: Readonly<Record<PipelineRunStatus, Tone>> = {
  pending: "neutral",
  running: "info",
  completed: "success",
  failed: "danger",
};

export function runStatusLabel(status: PipelineRunStatus): string {
  return t(STATUS_LABEL[status]);
}

export function runStatusTone(status: PipelineRunStatus): Tone {
  return STATUS_TONE[status];
}

export function pipelineCounts(runs: readonly PipelineRun[]): PipelineCounts {
  const counts = { total: runs.length, pending: 0, running: 0, completed: 0, failed: 0 };
  for (const run of runs) counts[run.status] += 1;
  return counts;
}

/** Whole seconds from start to finish; null until the run has both. */
export function runDurationSeconds(
  run: Pick<PipelineRun, "startedAt" | "finishedAt">,
): number | null {
  if (run.startedAt === null || run.finishedAt === null) return null;
  return Math.max(0, Math.round((Date.parse(run.finishedAt) - Date.parse(run.startedAt)) / 1000));
}

/** A duration in words: "45 s", "12 min 5 s" or "2 h 4 min". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return t("adminPipeline.duration.seconds", { seconds });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return t("adminPipeline.duration.minutes", { minutes, seconds: seconds % 60 });
  }
  return t("adminPipeline.duration.hours", {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
  });
}
