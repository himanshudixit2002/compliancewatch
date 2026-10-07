"use server";

import type { TaskKind } from "@/entities/pipeline/types";
import { idempotencyHeaders } from "@/server/api/idempotency";
import { pipelineWrites } from "@/server/api/pipeline-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import { documentTypeLabel } from "@/shared/ui/pipeline";
import { parseRetry, reasonOf, stageLabel } from "./model/document";
import { parseResolution } from "./model/tasks";
import { mayHaveRecorded, plainRefusal } from "./refusals";
import { DISMISS_FIELDS, REQUEUE_FIELDS, type WriteResult } from "./ui/pipeline-shared";

/**
 * The pipeline's operations: a stored document's retry from a stage (with the Idempotency-Key the
 * page was rendered with), a dead outbox row's requeue, and a task's resolution or dismissal. Each
 * runs its page's gate again (the proxy is not on an action's path), refuses anyone but an admin
 * (`admin.pipeline.control`) before any request, checks the form's shape, and goes through
 * `server/api/pipeline-write.ts`, which sends the shared write token and names the session's user
 * as the actor; the pipeline keeps the reason in its audit entry. Refusals are said plainly. On an
 * answer that may have recorded something, the pages render again.
 */
const PIPELINE = screenById("admin.pipeline");
const DOCUMENT = screenById("admin.pipeline.document");
const TASKS = screenById("admin.pipeline.tasks");

function adminOnly<T>(): ActionState<T> {
  return actionFailure(t("adminPipeline.access.adminOnly"));
}

function done(message: string): ActionState<WriteResult> {
  return actionSuccess({ message }, message);
}

/** Runs the stored document's ingest again from a stage, optionally as a type a person gives it. */
export async function retryDocument(
  documentId: string,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(DOCUMENT, { documentId });
  if (!can(session, "admin.pipeline.control")) return adminOnly();
  if (!isHexUuid(documentId)) return actionFailure(t("adminPipeline.refusal.documentNotFound"));
  const parsed = parseRetry(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const id = documentId.toLowerCase();
  const result = await pipelineWrites({ session }, "admin.pipeline.control").retryDocument(
    id,
    { stage: parsed.stage, docType: parsed.docType },
    parsed.reason,
    idempotencyHeaders(formData, "pipeline.retry-document"),
  );
  const refresh = () =>
    afterMutation({ paths: [hrefFor(DOCUMENT, { documentId: id }), hrefFor(PIPELINE)] });
  if (!result.ok) {
    if (mayHaveRecorded(result.error)) refresh();
    return plainRefusal<WriteResult>(result.error);
  }
  refresh();
  const { value, replayed } = result.value;
  const stage = stageLabel(value.retry.stage);
  const parts = [
    replayed
      ? t("pipelineDocument.retry.replayed", { attempt: value.retry.attempt, stage })
      : t("pipelineDocument.retry.recorded", { attempt: value.retry.attempt, stage }),
    value.started
      ? t("pipelineDocument.retry.started", { workflow: value.workflowId })
      : t("pipelineDocument.retry.startedBefore", { workflow: value.workflowId }),
  ];
  if (value.reclassified && value.retry.docType !== null) {
    parts.push(
      t("pipelineDocument.retry.reclassified", { type: documentTypeLabel(value.retry.docType) }),
    );
  }
  return done(parts.join(" "));
}

/** Puts a dead outbox row back to pending, so the relay sends it again on its next pass. */
export async function requeueEvent(
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(PIPELINE);
  if (!can(session, "admin.pipeline.control")) return adminOnly();
  const eventId = formData.get(REQUEUE_FIELDS.eventId);
  if (typeof eventId !== "string" || !isHexUuid(eventId)) {
    return actionFailure(t("adminPipeline.refusal.eventNotFound"));
  }
  const reason = reasonOf(formData, REQUEUE_FIELDS.reason);
  if (!reason.ok) return fieldFailure(reason.fieldErrors);
  const result = await pipelineWrites({ session }, "admin.pipeline.control").requeueEvent(
    eventId.toLowerCase(),
    reason.reason,
  );
  if (!result.ok) return plainRefusal<WriteResult>(result.error);
  afterMutation({ paths: [hrefFor(PIPELINE)] });
  return done(
    result.value.requeued
      ? t("adminPipeline.requeue.done", { topic: result.value.event.topic })
      : t("adminPipeline.requeue.notDead", { status: result.value.event.status }),
  );
}

/**
 * Resolves a task: a manual parse with the analyst's transcript, a triage with the decision. The
 * same resolution sent again (a lost answer, a second click) is answered as the first was, and is
 * said as a success.
 */
export async function resolveTask(
  taskId: string,
  kind: TaskKind,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASKS);
  if (!can(session, "admin.pipeline.control")) return adminOnly();
  if (!isHexUuid(taskId)) return actionFailure(t("pipelineTasks.refusal.notFound"));
  const parsed = parseResolution(kind, formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const result = await pipelineWrites({ session }, "admin.pipeline.control").resolveTask(
    taskId.toLowerCase(),
    "transcript" in parsed.resolution
      ? { transcript: parsed.resolution.transcript }
      : { triage: parsed.resolution.triage },
    parsed.reason,
  );
  if (!result.ok) {
    if (mayHaveRecorded(result.error))
      afterMutation({ paths: [hrefFor(TASKS), hrefFor(PIPELINE)] });
    return plainRefusal<WriteResult>(result.error);
  }
  afterMutation({ paths: [hrefFor(TASKS), hrefFor(PIPELINE)] });
  const { started, workflowId } = result.value;
  if (workflowId === "") return done(t("pipelineTasks.resolve.setAside"));
  return done(
    started
      ? t("pipelineTasks.resolve.started", { workflow: workflowId })
      : t("pipelineTasks.resolve.replayed", { workflow: workflowId }),
  );
}

/** Closes a task without the work, with the reason. */
export async function dismissTask(
  taskId: string,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASKS);
  if (!can(session, "admin.pipeline.control")) return adminOnly();
  if (!isHexUuid(taskId)) return actionFailure(t("pipelineTasks.refusal.notFound"));
  const reason = reasonOf(formData, DISMISS_FIELDS.reason);
  if (!reason.ok) return fieldFailure(reason.fieldErrors);
  const result = await pipelineWrites({ session }, "admin.pipeline.control").dismissTask(
    taskId.toLowerCase(),
    reason.reason,
  );
  if (!result.ok) return plainRefusal<WriteResult>(result.error);
  afterMutation({ paths: [hrefFor(TASKS), hrefFor(PIPELINE)] });
  return done(
    result.value.kind === "manual_parse"
      ? t("pipelineTasks.dismiss.doneManualParse")
      : t("pipelineTasks.dismiss.doneTriage"),
  );
}
