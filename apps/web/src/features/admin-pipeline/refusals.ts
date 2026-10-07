import "server-only";

import { isProblemOf } from "@/entities/problem/mappers";
import { toActionState, type ApiError } from "@/server/result";
import { t, type MessageKey } from "@/shared/i18n";
import type { ActionState } from "@/shared/lib/action-state";

/**
 * The pipeline's refusals of a retry, a requeue or a task's resolution, said plainly: what each
 * one means and what to do. A refusal whose detail names the case (which task holds a document,
 * which block of a transcript is wrong) keeps the pipeline's detail; the others take the page's.
 * The correlation id always stays.
 */
interface Wording {
  title: MessageKey;
  /** The page's detail; without one the pipeline's stays. */
  detail?: MessageKey;
}

const REFUSALS: Readonly<Record<string, Wording>> = {
  "pipeline-ingest-running": {
    title: "adminPipeline.refusal.ingestRunning",
    detail: "adminPipeline.refusal.ingestRunningDetail",
  },
  "pipeline-retry-refused": { title: "adminPipeline.refusal.retryRefused" },
  "pipeline-retry-invalid": {
    title: "adminPipeline.refusal.retryInvalid",
    detail: "adminPipeline.refusal.retryInvalidDetail",
  },
  "idempotency-key-reused": {
    title: "adminPipeline.refusal.keyReused",
    detail: "adminPipeline.refusal.keyReusedDetail",
  },
  "idempotency-key-required": {
    title: "adminPipeline.refusal.keyRequired",
    detail: "adminPipeline.refusal.keyRequiredDetail",
  },
  "idempotency-request-in-flight": {
    title: "adminPipeline.refusal.inFlight",
    detail: "adminPipeline.refusal.inFlightDetail",
  },
  "pipeline-ingest-unavailable": {
    title: "adminPipeline.refusal.temporal",
    detail: "adminPipeline.refusal.temporalDetail",
  },
  "pipeline-outbox-event-not-found": {
    title: "adminPipeline.refusal.eventNotFound",
    detail: "adminPipeline.refusal.eventNotFoundDetail",
  },
  "pipeline-document-not-found": { title: "adminPipeline.refusal.documentNotFound" },
  "pipeline-task-closed": {
    title: "pipelineTasks.refusal.closed",
    detail: "pipelineTasks.refusal.closedDetail",
  },
  "pipeline-task-not-found": { title: "pipelineTasks.refusal.notFound" },
  "pipeline-task-resolution-invalid": { title: "pipelineTasks.refusal.resolutionInvalid" },
  "pipeline-transcript-invalid": { title: "pipelineTasks.refusal.transcriptInvalid" },
};

/** The refusal as a form shows it: in the page's words when the page knows it. */
export function plainRefusal<T>(error: ApiError): ActionState<T> {
  const state = toActionState<T>({ ok: false, error });
  if (state.status !== "error" || state.problem === undefined) return state;
  for (const [slug, wording] of Object.entries(REFUSALS)) {
    if (!isProblemOf(error.problem, slug)) continue;
    const detail = wording.detail === undefined ? state.problem.detail : t(wording.detail);
    return {
      ...state,
      problem: {
        ...state.problem,
        title: t(wording.title),
        ...(detail === undefined ? {} : { detail }),
      },
    };
  }
  return state;
}

/** Whether the refusal may have left something recorded, so the page should render again. */
export function mayHaveRecorded(error: ApiError): boolean {
  return isProblemOf(error.problem, "pipeline-ingest-unavailable") || error.kind === "network";
}
