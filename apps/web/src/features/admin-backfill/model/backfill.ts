import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The backfill screen's model: jobs that rebuild a service's derived data from its source
 * records, with how far each has got. `POST /v1/pipeline/backfills` has no design yet (`make
 * backfill SERVICE=pipeline` is the current path), so the shape is the screen's own.
 */
export type BackfillStatus = "pending" | "running" | "completed" | "failed";

export const BACKFILL_STATUSES: readonly BackfillStatus[] = [
  "pending",
  "running",
  "completed",
  "failed",
];

export interface BackfillJob {
  id: string;
  /** What the job rebuilds, for example "Applicability decisions". */
  name: string;
  /** The service whose data it rebuilds. */
  service: string;
  status: BackfillStatus;
  /** Records rebuilt so far. */
  processed: number;
  /** Records to rebuild; null until the job has counted them. */
  total: number | null;
  /** When it started, an ISO instant; null until it has. */
  startedAt: string | null;
  /** When it completed or failed, an ISO instant; null until it has. */
  finishedAt: string | null;
}

/** How many jobs there are in all and in each status. */
export type BackfillCounts = Readonly<Record<BackfillStatus | "total", number>>;

const STATUS_LABEL: Readonly<Record<BackfillStatus, MessageKey>> = {
  pending: "adminBackfill.status.pending",
  running: "adminBackfill.status.running",
  completed: "adminBackfill.status.completed",
  failed: "adminBackfill.status.failed",
};

const STATUS_TONE: Readonly<Record<BackfillStatus, Tone>> = {
  pending: "neutral",
  running: "info",
  completed: "success",
  failed: "danger",
};

export function backfillStatusLabel(status: BackfillStatus): string {
  return t(STATUS_LABEL[status]);
}

export function backfillStatusTone(status: BackfillStatus): Tone {
  return STATUS_TONE[status];
}

export function backfillCounts(jobs: readonly BackfillJob[]): BackfillCounts {
  const counts = { total: jobs.length, pending: 0, running: 0, completed: 0, failed: 0 };
  for (const job of jobs) counts[job.status] += 1;
  return counts;
}
