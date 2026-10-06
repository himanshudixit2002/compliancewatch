import "server-only";

import { uploadStoredFromDto } from "@/entities/pipeline/mappers";
import { DOCUMENT_TYPES, type DocumentType, type UploadFormDto } from "@/entities/pipeline/types";
import { isProblemOf } from "@/entities/problem/mappers";
import type { ValidationIssue } from "@/entities/problem/types";
import type { SessionClaims } from "@/entities/session/types";
import { isRegulatory } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import { isDateKey } from "@/shared/lib/dates";
import { call, type FetchImpl } from "../api/client";
import { explainPipelineTokenProblem, pipelineWriteClient } from "../api/pipeline-write";
import { getEnv } from "../env";
import { isSameOriginRequest } from "../origin";
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
 * - a request from another site is refused (`server/origin.ts`, the sign-out handler's check), so a
 *   foreign page cannot make an admin's browser upload;
 * - no session is a 401, a tenant role a 404 (the tool does not exist for it), a regulatory role
 *   other than the admin a 403, and a server without the write token a 503, from
 *   `server/api/pipeline-write.ts`, the only module that sends the pipeline that token;
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
 * from the service's code.
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

/** The time limit of the whole exchange: the body streams up, then Temporal may take ten seconds. */
export const UPLOAD_TIMEOUT_MS = 120_000;

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

/** A pipeline refusal of the upload, in plain words. */
function refused(error: ApiError, sha256: string | null, max: number): Response {
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
      detail: t("upload.error.tooLargeDetail", { limit: megabytes(max) }),
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

/** The handler's answer to an upload request. */
export async function uploadResponse(
  request: Request,
  key: string,
  session: SessionClaims | null,
  deps: UploadDeps = {},
): Promise<Response> {
  const env = getEnv();
  if (
    !isSameOriginRequest(request.headers, { trustForwardedHost: env.CW_WEB_TRUST_FORWARDED_IP })
  ) {
    return problemResponse({
      slug: "web-cross-origin-request",
      status: 403,
      title: t("upload.error.crossOrigin"),
      detail: t("upload.error.crossOriginDetail"),
    });
  }
  if (session === null) {
    return problemResponse({
      slug: "web-sign-in-required",
      status: 401,
      title: t("upload.error.signIn"),
      detail: t("upload.error.signInDetail"),
    });
  }
  if (!isRegulatory(session)) {
    return problemResponse({
      slug: "web-not-found",
      status: 404,
      title: t("upload.error.notFound"),
    });
  }
  const max = env.CW_WEB_PIPELINE_UPLOAD_MAX_BYTES;
  const client = pipelineWriteClient(
    { session, fetchImpl: deps.fetchImpl },
    "admin.sources.write",
    { timeoutMs: UPLOAD_TIMEOUT_MS },
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
  const sent = fileBody(head, reader, prefix, outgoing, max);
  // The typed body names what the multipart parts carry; the serializer sends the stream instead.
  const typed: UploadFormDto = {
    actor_id: session.userId,
    reason: fields.reason,
    file: `document.${extension}`,
  };
  const result = await call(
    client.value.POST("/v1/pipeline/sources/{key}/uploads", {
      params: { path: { key } },
      body: typed,
      bodySerializer: () => sent.stream,
      headers: { "content-type": `multipart/form-data; boundary=${outgoing}` },
      signal: request.signal,
      // A streamed request body needs half duplex in Node's fetch.
      ...({ duplex: "half" } as Record<string, string>),
    }),
  );
  const failure = sent.failure();
  if (failure !== null) return failure.failure === "too_large" ? tooLarge(max) : malformed();
  const stored = mapBody(result, uploadStoredFromDto);
  if (!stored.ok) return refused(stored.error, sent.sha256(), max);
  return new Response(JSON.stringify(stored.value), {
    status: 202,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}
