import "server-only";

import type { pipeline } from "@compliancewatch/contracts/openapi";
import {
  fetchStartedFromDto,
  requeuedFromDto,
  retryAcceptedFromDto,
  sourceEditToDto,
  sourceFromDto,
  taskFromDto,
  taskResolvedFromDto,
  transcriptToDto,
  triageToDto,
} from "@/entities/pipeline/mappers";
import type {
  DocumentType,
  FetchStarted,
  PipelineSource,
  PipelineTask,
  Requeued,
  RetryAccepted,
  RetryStage,
  SourceEdit,
  TaskResolved,
  Transcript,
  TriageDecision,
} from "@/entities/pipeline/types";
import { isProblemOf } from "@/entities/problem/mappers";
import { can, type Capability } from "@/shared/config/permissions";
import { t } from "@/shared/i18n";
import { getEnv, serviceUrl } from "../env";
import { err, mapBody, mapResult, ok, webError, type ApiError, type Result } from "../result";
import { WRITE_TOKEN_HEADER, call, createServiceClient, type FetchImpl } from "./client";
import { callIdempotent, type Replayable } from "./idempotency";
import type { ClientContext, PipelineClient } from "./services";

/**
 * The pipeline's writes, and the only module that sends the pipeline the shared write token: the
 * web app's CW_WEB_RULEBOOK_WRITE_TOKEN, which is the value the pipeline reads as its copy of the
 * rulebook's CW_RULEBOOK_WRITE_TOKEN and takes in `x-cw-write-token` while its CW_AUTH_MODE is
 * header or dual. Every pipeline write is an admin's (the source manager's and the operations'
 * routes take an admin a token names, or the shared token), so the client is refused before any
 * request to a session without the capability the write asks for, and to a server without the
 * token. Each body names the session's user as `actor_id` and carries the admin's reason, which
 * the pipeline keeps verbatim in its audit entry; a form never names the actor.
 *
 * The writes that start a workflow (a fetch, a retry, a task's resolution, an upload) wait for
 * Temporal on the pipeline's side for up to ten seconds before it answers 503, so their calls
 * have a longer time limit than a read: at least `PIPELINE_WRITE_TIMEOUT_MS`. A pipeline refusal
 * about the token (wrong: 401; none configured on the pipeline: 503) is reworded to say which side
 * to fix, naming the variable and never its value; every other refusal passes on as it came.
 */
export const PIPELINE_WRITE_TIMEOUT_MS = 30_000;

export type PipelineWriteCapability = Extract<
  Capability,
  "admin.sources.write" | "admin.pipeline.control"
>;

const TOKEN_PROBLEMS = {
  "pipeline-write-token-invalid": {
    title: () => t("pipelineWrites.tokenInvalid"),
    detail: () => t("pipelineWrites.tokenInvalidDetail"),
  },
  "pipeline-writes-disabled": {
    title: () => t("pipelineWrites.writesDisabled"),
    detail: () => t("pipelineWrites.writesDisabledDetail"),
  },
} as const;

/** A pipeline refusal about the write token, reworded; any other error passes unchanged. */
export function explainPipelineTokenProblem(error: ApiError): ApiError {
  for (const [slug, wording] of Object.entries(TOKEN_PROBLEMS)) {
    if (error.problem !== undefined && isProblemOf(error.problem, slug)) {
      const title = wording.title();
      return {
        ...error,
        message: title,
        problem: { ...error.problem, title, detail: wording.detail() },
      };
    }
  }
  return error;
}

function explained<T>(result: Result<T>): Result<T> {
  return result.ok ? result : err(explainPipelineTokenProblem(result.error));
}

export interface PipelineWriteOptions {
  /** A time limit instead of the write default. */
  timeoutMs?: number;
  /**
   * `caller` leaves every limit to the call's own signal: an upload times the browser's stream
   * and the wait for the pipeline's answer itself (server/bff/upload.ts).
   */
  timeoutScope?: "exchange" | "caller";
  fetchImpl?: FetchImpl;
}

/**
 * The pipeline client with the write token, for a session holding the capability; otherwise
 * the refusal (the admin role, or the token not configured), decided before any request.
 */
export function pipelineWriteClient(
  ctx: ClientContext,
  capability: PipelineWriteCapability,
  options: PipelineWriteOptions = {},
): Result<PipelineClient> {
  if (!can(ctx.session, capability)) {
    return err(
      webError(
        "forbidden",
        "web-admin-role-required",
        t("pipelineWrites.adminRequired"),
        t("pipelineWrites.adminRequiredDetail"),
      ),
    );
  }
  const env = getEnv();
  const token = env.CW_WEB_RULEBOOK_WRITE_TOKEN;
  if (token === undefined) {
    return err(
      webError(
        "unavailable",
        "web-write-token-missing",
        t("pipelineWrites.tokenMissing"),
        t("pipelineWrites.tokenMissingDetail"),
      ),
    );
  }
  return ok(
    createServiceClient<pipeline.paths>({
      service: "pipeline",
      baseUrl: serviceUrl("pipeline", env),
      timeoutMs:
        options.timeoutMs ?? Math.max(env.CW_WEB_REQUEST_TIMEOUT_MS, PIPELINE_WRITE_TIMEOUT_MS),
      timeoutScope: options.timeoutScope ?? "exchange",
      fetchImpl: options.fetchImpl ?? ctx.fetchImpl,
      // No tenant header: the pipeline's records belong to no tenant.
      headers: { [WRITE_TOKEN_HEADER]: token },
    }),
  );
}

type KeyHeader = { "Idempotency-Key": string };

/** A retry's request: the stage, and the type a person gives it (null: its classification stands). */
export interface RetryRequest {
  stage: RetryStage;
  docType: DocumentType | null;
}

/** A task's resolution: a transcript for a manual parse, a decision for a triage. */
export type TaskResolution = { transcript: Transcript } | { triage: TriageDecision };

/** The pipeline writes the admin tools send, each with the admin's reason. */
export interface PipelineWritePort {
  editSource(key: string, edit: SourceEdit, reason: string): Promise<Result<PipelineSource>>;
  fetchSource(key: string, reason: string): Promise<Result<FetchStarted>>;
  /** `headers` carries the Idempotency-Key the form was rendered with. */
  retryDocument(
    documentId: string,
    request: RetryRequest,
    reason: string,
    headers: Readonly<Record<string, string>>,
  ): Promise<Result<Replayable<RetryAccepted>>>;
  requeueEvent(eventId: string, reason: string): Promise<Result<Requeued>>;
  resolveTask(
    taskId: string,
    resolution: TaskResolution,
    reason: string,
  ): Promise<Result<TaskResolved>>;
  dismissTask(taskId: string, reason: string): Promise<Result<PipelineTask>>;
}

/** The writes over the token client, with `actor_id` from the session. */
export class PipelineWriteGateway implements PipelineWritePort {
  private readonly client: PipelineClient;
  private readonly actorId: string;

  constructor(client: PipelineClient, actorId: string) {
    this.client = client;
    this.actorId = actorId;
  }

  async editSource(key: string, edit: SourceEdit, reason: string): Promise<Result<PipelineSource>> {
    const result = await call(
      this.client.PATCH("/v1/pipeline/sources/{key}", {
        params: { path: { key } },
        body: sourceEditToDto(edit, this.actorId, reason),
      }),
    );
    return explained(mapBody(result, sourceFromDto));
  }

  async fetchSource(key: string, reason: string): Promise<Result<FetchStarted>> {
    const result = await call(
      this.client.POST("/v1/pipeline/sources/{key}/fetch", {
        params: { path: { key } },
        body: { actor_id: this.actorId, reason },
      }),
    );
    return explained(mapBody(result, fetchStartedFromDto));
  }

  async retryDocument(
    documentId: string,
    request: RetryRequest,
    reason: string,
    headers: Readonly<Record<string, string>>,
  ): Promise<Result<Replayable<RetryAccepted>>> {
    const result = await callIdempotent(
      this.client.POST("/v1/pipeline/documents/{document_id}/retry", {
        // The Idempotency-Key the form was rendered with; `idempotencyHeaders` gives it only for
        // a key that is a UUID, and the pipeline answers 428 without one.
        params: { path: { document_id: documentId }, header: headers as KeyHeader },
        body: {
          actor_id: this.actorId,
          reason,
          stage: request.stage,
          ...(request.docType === null ? {} : { doc_type: request.docType }),
        },
      }),
    );
    if (!result.ok) return explained(result);
    const { replayed } = result.value;
    return mapBody(
      mapResult(result, (answer) => answer.value),
      (value) => ({ value: retryAcceptedFromDto(value), replayed }),
    );
  }

  async requeueEvent(eventId: string, reason: string): Promise<Result<Requeued>> {
    const result = await call(
      this.client.POST("/v1/pipeline/outbox/{event_id}/requeue", {
        params: { path: { event_id: eventId } },
        body: { actor_id: this.actorId, reason },
      }),
    );
    return explained(mapBody(result, requeuedFromDto));
  }

  async resolveTask(
    taskId: string,
    resolution: TaskResolution,
    reason: string,
  ): Promise<Result<TaskResolved>> {
    const result = await call(
      this.client.POST("/v1/pipeline/tasks/{task_id}/resolve", {
        params: { path: { task_id: taskId } },
        body: {
          actor_id: this.actorId,
          reason,
          ...("transcript" in resolution
            ? { transcript: transcriptToDto(resolution.transcript) }
            : { triage: triageToDto(resolution.triage) }),
        },
      }),
    );
    return explained(mapBody(result, taskResolvedFromDto));
  }

  async dismissTask(taskId: string, reason: string): Promise<Result<PipelineTask>> {
    const result = await call(
      this.client.POST("/v1/pipeline/tasks/{task_id}/dismiss", {
        params: { path: { task_id: taskId } },
        body: { actor_id: this.actorId, reason },
      }),
    );
    return explained(mapBody(result, taskFromDto));
  }
}

/** A port that refuses every write with the same error and sends nothing. */
export class RefusedPipelineWrites implements PipelineWritePort {
  readonly error: ApiError;

  constructor(error: ApiError) {
    this.error = error;
  }

  async editSource(): Promise<Result<PipelineSource>> {
    return err(this.error);
  }

  async fetchSource(): Promise<Result<FetchStarted>> {
    return err(this.error);
  }

  async retryDocument(): Promise<Result<Replayable<RetryAccepted>>> {
    return err(this.error);
  }

  async requeueEvent(): Promise<Result<Requeued>> {
    return err(this.error);
  }

  async resolveTask(): Promise<Result<TaskResolved>> {
    return err(this.error);
  }

  async dismissTask(): Promise<Result<PipelineTask>> {
    return err(this.error);
  }
}

/**
 * The writes an admin action makes, for a session holding the capability with the token set;
 * otherwise a port whose every method answers the refusal without a request.
 */
export function pipelineWrites(
  ctx: ClientContext,
  capability: PipelineWriteCapability,
): PipelineWritePort {
  const client = pipelineWriteClient(ctx, capability);
  if (!client.ok) return new RefusedPipelineWrites(client.error);
  return new PipelineWriteGateway(client.value, ctx.session?.userId ?? "");
}

export type PipelineWriteAccess = { allowed: true } | { allowed: false; error: ApiError };

/** Whether a page may offer the writes of a capability, and if not, the refusal to show. */
export function pipelineWriteAccess(
  ctx: ClientContext,
  capability: PipelineWriteCapability,
): PipelineWriteAccess {
  const client = pipelineWriteClient(ctx, capability);
  return client.ok ? { allowed: true } : { allowed: false, error: client.error };
}
