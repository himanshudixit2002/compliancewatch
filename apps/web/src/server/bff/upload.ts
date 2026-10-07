import "server-only";

import { uploadStoredFromDto } from "@/entities/pipeline/mappers";
import { DOCUMENT_TYPES, type DocumentType, type UploadFormDto } from "@/entities/pipeline/types";
import { isProblemOf } from "@/entities/problem/mappers";
import type { ValidationIssue } from "@/entities/problem/types";
import type { SessionClaims } from "@/entities/session/types";
import { t } from "@/shared/i18n";
import { isDateKey } from "@/shared/lib/dates";
import { call, type FetchImpl } from "../api/client";
import { explainPipelineTokenProblem, pipelineWriteClient } from "../api/pipeline-write";
import { getEnv } from "../env";
import { mapBody, type ApiError } from "../result";
import {
  UploadFormError,
  boundaryOf,
  fileBody,
  filePartHead,
  newBoundary,
  readUploadHead,
  textPart,
} from "./multipart";
import { apiErrorResponse, problemResponse } from "./problem";

/**
 * `POST /api-bff/pipeline/sources/{key}/uploads` (system.uploads): an admin's upload of a document
 * to a source, forwarded to the pipeline's `POST /v1/pipeline/sources/{key}/uploads` as it
 * arrives. The checks, in order, before a byte of the body is read:
 *
 * - the route file's gate, run before this (server/bff/gate.ts with the registry entry): a request
 *   from another site is refused (the sign-out handler's origin check), so a foreign page cannot
 *   make an admin's browser upload; no session is a 401, a tenant role a 404 (the tool does not
 *   exist for it) and a regulatory role other than the admin a 403;
 * - a server without the write token is a 503, from `server/api/pipeline-write.ts`, the only module
 *   that sends the pipeline that token (and which refuses a session without
 *   `admin.sources.write`, as the gate already has);
 * - a key that cannot be a source's is a 404, a body that is not multipart a 415, and a declared
 *   length past the limit a 413.
 *
 * Then the form's head is read (the fields come first, the file last, as the upload form sends
 * them): the file's declared type must be a PDF or an HTML page (415), and the reason (10 to 2000
 * characters), the title, the reference, the publication date and the document type are checked
 * as the pipeline checks them (a 422 names each field). The body sent on is new: the session's
 * user as `actor_id`, the checked fields, and the file's bytes streamed through untouched, counted
 * against the limit and hashed on the way. The limits are the pipeline's: its
 * CW_PIPELINE_UPLOAD_MAX_BYTES as the web app's CW_WEB_PIPELINE_UPLOAD_MAX_BYTES (25 MB by
 * default), and its 64 KiB allowance for the fields; upload.test.ts reads both, and the types,
 * from the service's code. A pipeline configured lower refuses on its own, and its refusal keeps
 * its detail, which names its limit; this server's number names only this server's refusal.
 *
 * Time (`UPLOAD_TIMING`): while the file streams on, only a stall stops it (no byte from the
 * browser for 30 seconds), never the file's size over a slow link; once the closing delimiter is
 * sent, the pipeline has 60 seconds to answer. A stall is a 400 (the pipeline never had the whole
 * body, so it stored nothing), and no answer in time a 504 (it may have stored the file).
 *
 * The answer: 202 with the stored document, whether its bytes were stored before, and the ingest's
 * workflow; or a problem in plain words. When Temporal does not answer, the pipeline has stored
 * the document but not started its ingest (503): the problem then carries `document_id`, the id
 * the pipeline gives those bytes (the first half of their SHA-256), so the page can link to it.
 */
export const UPLOAD_TYPES: Readonly<Record<string, string>> = {
  "application/pdf": "pdf",
  "text/html": "html",
  "application/xhtml+xml": "xhtml",
};

/** Room in the body for the fields beside the file: the pipeline's FORM_ALLOWANCE. */
export const FORM_ALLOWANCE = 64 * 1024;

/**
 * The upload's time limits. While the file streams up from the browser only a stall stops it: no
 * byte for `stallMs`, so a slow link that keeps sending is never cut, whatever the file's size.
 * Once the closing delimiter is sent, the pipeline stores the file, records it and waits up to
 * ten seconds for Temporal; `answerMs` covers that wait for its answer, and only that.
 */
export interface UploadTiming {
  stallMs: number;
  answerMs: number;
}

export const UPLOAD_TIMING: UploadTiming = { stallMs: 30_000, answerMs: 60_000 };

export const UPLOAD_LIMITS = {
  reasonMin: 10,
  reasonMax: 2000,
  titleMax: 2000,
  externalRefMax: 200,
} as const;

/** The form's field names, the pipeline's own. */
export const UPLOAD_FIELDS = {
  file: "file",
  reason: "reason",
  title: "title",
  publishedOn: "published_on",
  externalRef: "external_ref",
  documentType: "document_type",
} as const;

const SOURCE_KEY = /^[a-z][a-z0-9_]{0,62}$/;

export interface UploadDeps {
  fetchImpl?: FetchImpl;
  /** Shorter limits, for the tests. */
  timing?: Partial<UploadTiming>;
}

export interface UploadFields {
  reason: string;
  title: string;
  externalRef: string;
  publishedOn: string | null;
  documentType: DocumentType | null;
}

function issue(field: string, msg: string): ValidationIssue {
  return { loc: ["body", field], msg, type: "value_error" };
}

/** The form's text fields checked as the pipeline checks them, or the issues per field. */
export function checkUploadFields(
  fields: ReadonlyMap<string, string>,
): { ok: true; fields: UploadFields } | { ok: false; issues: ValidationIssue[] } {
  const text = (name: string) => (fields.get(name) ?? "").trim();
  const issues: ValidationIssue[] = [];
  const reason = text(UPLOAD_FIELDS.reason);
  if (reason.length < UPLOAD_LIMITS.reasonMin) {
    issues.push(
      issue(UPLOAD_FIELDS.reason, t("upload.error.reasonShort", { min: UPLOAD_LIMITS.reasonMin })),
    );
  } else if (reason.length > UPLOAD_LIMITS.reasonMax) {
    issues.push(
      issue(UPLOAD_FIELDS.reason, t("upload.error.reasonLong", { max: UPLOAD_LIMITS.reasonMax })),
    );
  }
  const title = text(UPLOAD_FIELDS.title);
  if (title.length > UPLOAD_LIMITS.titleMax) {
    issues.push(
      issue(UPLOAD_FIELDS.title, t("upload.error.titleLong", { max: UPLOAD_LIMITS.titleMax })),
    );
  }
  const externalRef = text(UPLOAD_FIELDS.externalRef);
  if (externalRef.length > UPLOAD_LIMITS.externalRefMax) {
    issues.push(
      issue(
        UPLOAD_FIELDS.externalRef,
        t("upload.error.refLong", { max: UPLOAD_LIMITS.externalRefMax }),
      ),
    );
  }
  const published = text(UPLOAD_FIELDS.publishedOn);
  if (published !== "" && !isDateKey(published)) {
    issues.push(issue(UPLOAD_FIELDS.publishedOn, t("upload.error.date")));
  }
  const type = text(UPLOAD_FIELDS.documentType);
  const documentType = (DOCUMENT_TYPES as readonly string[]).includes(type)
    ? (type as DocumentType)
    : null;
  if (type !== "" && documentType === null) {
    issues.push(issue(UPLOAD_FIELDS.documentType, t("upload.error.type")));
  }
  if (issues.length > 0) return { ok: false, issues };
  return {
    ok: true,
    fields: {
      reason,
      title,
      externalRef,
      publishedOn: published === "" ? null : published,
      documentType,
    },
  };
}

/** The document id the pipeline gives bytes of this SHA-256: its first 32 hex digits as a UUID. */
export function documentIdOf(sha256: string): string {
  const hex = sha256.slice(0, 32);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** "25 MB": a byte count in whole megabytes (10^6), as the pipeline states its limit. */
export function megabytes(bytes: number): string {
  return `${Math.floor(bytes / 1_000_000)} MB`;
}

function tooLarge(max: number): Response {
  return problemResponse({
    slug: "web-upload-too-large",
    status: 413,
    title: t("upload.error.tooLarge"),
    detail: t("upload.error.tooLargeDetail", { limit: megabytes(max) }),
  });
}

function malformed(): Response {
  return problemResponse({
    slug: "web-upload-malformed",
    status: 400,
    title: t("upload.error.malformed"),
    detail: t("upload.error.malformedDetail"),
  });
}

function unsupported(sent: string | null): Response {
  return problemResponse({
    slug: "web-upload-unsupported",
    status: 415,
    title: t("upload.error.unsupported"),
    detail:
      sent === null || sent === ""
        ? t("upload.error.unsupportedNone")
        : t("upload.error.unsupportedDetail", { type: sent }),
  });
}

function stalled(timing: UploadTiming): Response {
  return problemResponse({
    slug: "web-upload-stalled",
    status: 400,
    title: t("upload.error.stalled"),
    detail: t("upload.error.stalledDetail", { seconds: Math.round(timing.stallMs / 1000) }),
  });
}

function unanswered(timing: UploadTiming): Response {
  return problemResponse({
    slug: "web-upload-unanswered",
    status: 504,
    title: t("upload.error.unanswered"),
    detail: t("upload.error.unansweredDetail", { seconds: Math.round(timing.answerMs / 1000) }),
  });
}

export type UploadExpiry = "stalled" | "unanswered";

export interface UploadClock {
  /** Aborts the call to the pipeline when a limit passes. */
  signal: AbortSignal;
  /** Bytes arrived from the browser: the stall limit starts again. */
  progress(): void;
  /** The closing delimiter is sent: from now on only the wait for the answer is timed. */
  sent(): void;
  /** Which limit passed, if one did. */
  expired(): UploadExpiry | null;
  stop(): void;
}

/**
 * The two limits of an upload on one signal: the stall limit while the file streams, restarted by
 * every chunk from the browser (a pipeline that stops reading stops the reads too, so it counts as
 * a stall), then the wait for the answer once the body is sent.
 */
export function uploadClock(timing: UploadTiming): UploadClock {
  const controller = new AbortController();
  let expiry: UploadExpiry | null = null;
  let answering = false;
  let handle: ReturnType<typeof setTimeout> | undefined;
  const arm = (ms: number, why: UploadExpiry) => {
    clearTimeout(handle);
    if (controller.signal.aborted) return;
    handle = setTimeout(() => {
      expiry = why;
      controller.abort(new DOMException(`the upload ${why} after ${ms} ms`, "TimeoutError"));
    }, ms);
  };
  arm(timing.stallMs, "stalled");
  return {
    signal: controller.signal,
    progress: () => {
      if (!answering) arm(timing.stallMs, "stalled");
    },
    sent: () => {
      answering = true;
      arm(timing.answerMs, "unanswered");
    },
    expired: () => expiry,
    stop: () => clearTimeout(handle),
  };
}

/**
 * The pipeline's own size refusal in words: its detail names its own limit (which may be lower
 * than this server's CW_WEB_PIPELINE_UPLOAD_MAX_BYTES), so it is kept rather than replaced by this
 * server's number.
 */
export function pipelineTooLargeDetail(detail: string | null | undefined): string {
  const said = (detail ?? "").trim().replace(/[.\s]+$/, "");
  return said === ""
    ? t("upload.error.tooLargePipeline")
    : t("upload.error.tooLargePipelineDetail", { detail: said });
}

/** A pipeline refusal of the upload, in plain words. */
function refused(error: ApiError, sha256: string | null): Response {
  const explained = explainPipelineTokenProblem(error);
  const problem = explained.problem;
  if (isProblemOf(problem, "pipeline-ingest-unavailable")) {
    return apiErrorResponse(
      explained,
      { title: t("upload.error.notStarted"), detail: t("upload.error.notStartedDetail") },
      sha256 === null ? undefined : { document_id: documentIdOf(sha256) },
    );
  }
  if (isProblemOf(problem, "pipeline-upload-too-large")) {
    return apiErrorResponse(explained, {
      title: t("upload.error.tooLarge"),
      detail: pipelineTooLargeDetail(problem?.detail),
    });
  }
  if (isProblemOf(problem, "pipeline-upload-unsupported")) {
    return apiErrorResponse(explained, { title: t("upload.error.unsupported") });
  }
  if (isProblemOf(problem, "pipeline-source-not-found")) {
    return apiErrorResponse(explained, {
      title: t("upload.error.noSource"),
      detail: t("upload.error.noSourceDetail"),
    });
  }
  if (explained.kind === "network") {
    return apiErrorResponse(explained, {
      title: t("upload.error.unreachable"),
      detail: t("upload.error.unreachableDetail"),
    });
  }
  return apiErrorResponse(explained);
}

/** The handler's answer to an upload request, for the session the route's gate let through. */
export async function uploadResponse(
  request: Request,
  key: string,
  session: SessionClaims,
  deps: UploadDeps = {},
): Promise<Response> {
  const env = getEnv();
  const max = env.CW_WEB_PIPELINE_UPLOAD_MAX_BYTES;
  const timing: UploadTiming = { ...UPLOAD_TIMING, ...deps.timing };
  // No limit of the client's own: the clock below times the stream and the answer.
  const client = pipelineWriteClient(
    { session, fetchImpl: deps.fetchImpl },
    "admin.sources.write",
    { timeoutMs: timing.answerMs, timeoutScope: "caller" },
  );
  if (!client.ok) return apiErrorResponse(client.error);
  if (!SOURCE_KEY.test(key)) {
    return problemResponse({
      slug: "web-not-found",
      status: 404,
      title: t("upload.error.noSource"),
      detail: t("upload.error.noSourceDetail"),
    });
  }
  const boundary = boundaryOf(request.headers.get("content-type"));
  if (boundary === null || request.body === null) {
    return problemResponse({
      slug: "web-upload-not-multipart",
      status: 415,
      title: t("upload.error.notMultipart"),
      detail: t("upload.error.notMultipartDetail"),
    });
  }
  const declared = request.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > max + FORM_ALLOWANCE) {
    return tooLarge(max);
  }

  const reader = request.body.getReader();
  let head;
  try {
    head = await readUploadHead(reader, boundary, FORM_ALLOWANCE, UPLOAD_FIELDS.file);
  } catch (error) {
    void reader.cancel().catch(() => undefined);
    if (error instanceof UploadFormError) {
      return error.failure === "too_large" ? tooLarge(max) : malformed();
    }
    throw error;
  }
  const fileType = (head.file.contentType ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  const extension = UPLOAD_TYPES[fileType];
  if (extension === undefined) {
    void reader.cancel().catch(() => undefined);
    return unsupported(head.file.contentType);
  }
  const checked = checkUploadFields(head.fields);
  if (!checked.ok) {
    void reader.cancel().catch(() => undefined);
    return problemResponse({
      slug: "web-upload-invalid",
      status: 422,
      title: t("upload.error.fields"),
      errors: checked.issues,
    });
  }

  const fields = checked.fields;
  const outgoing = newBoundary();
  const prefix = Buffer.concat([
    textPart(outgoing, "actor_id", session.userId),
    textPart(outgoing, UPLOAD_FIELDS.reason, fields.reason),
    ...(fields.title === "" ? [] : [textPart(outgoing, UPLOAD_FIELDS.title, fields.title)]),
    ...(fields.externalRef === ""
      ? []
      : [textPart(outgoing, UPLOAD_FIELDS.externalRef, fields.externalRef)]),
    ...(fields.publishedOn === null
      ? []
      : [textPart(outgoing, UPLOAD_FIELDS.publishedOn, fields.publishedOn)]),
    ...(fields.documentType === null
      ? []
      : [textPart(outgoing, UPLOAD_FIELDS.documentType, fields.documentType)]),
    filePartHead(outgoing, `document.${extension}`, fileType),
  ]);
  // The clock starts with the forwarding: the stall limit while the browser's bytes flow on, the
  // wait for the answer once the closing delimiter is sent. The browser going away stops it too.
  const clock = uploadClock(timing);
  const sent = fileBody(head, reader, prefix, outgoing, max, {
    onBytes: clock.progress,
    onEnd: clock.sent,
  });
  // The typed body names what the multipart parts carry; the serializer sends the stream instead.
  const typed: UploadFormDto = {
    actor_id: session.userId,
    reason: fields.reason,
    file: `document.${extension}`,
  };
  let result;
  try {
    result = await call(
      client.value.POST("/v1/pipeline/sources/{key}/uploads", {
        params: { path: { key } },
        body: typed,
        bodySerializer: () => sent.stream,
        headers: { "content-type": `multipart/form-data; boundary=${outgoing}` },
        signal: AbortSignal.any([request.signal, clock.signal]),
        // A streamed request body needs half duplex in Node's fetch.
        ...({ duplex: "half" } as Record<string, string>),
      }),
    );
  } finally {
    clock.stop();
  }
  // A limit that passed comes first: what the stream did after the abort is its consequence.
  const expiry = result.ok ? null : clock.expired();
  if (expiry === "stalled") return stalled(timing);
  if (expiry === "unanswered") return unanswered(timing);
  const failure = sent.failure();
  if (failure !== null) return failure.failure === "too_large" ? tooLarge(max) : malformed();
  const stored = mapBody(result, uploadStoredFromDto);
  if (!stored.ok) return refused(stored.error, sent.sha256());
  return new Response(JSON.stringify(stored.value), {
    status: 202,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}
