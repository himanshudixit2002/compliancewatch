import "server-only";

import type { pipeline } from "@compliancewatch/contracts/openapi";
import { storedDocumentFromDto } from "@/entities/pipeline/mappers";
import type { StoredDocument } from "@/entities/pipeline/types";
import type { SessionClaims } from "@/entities/session/types";
import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";
import { call, createServiceClient, type FetchImpl } from "../api/client";
import { pipelineClient } from "../api/services";
import { getEnv, serviceUrl } from "../env";
import { mapBody, type ApiError } from "../result";
import { apiErrorResponse, problemResponse } from "./problem";

/**
 * `GET /api-bff/pipeline/documents/{documentId}/raw` (system.raw-document): a stored document's
 * bytes from the pipeline's raw store, streamed to the browser as they arrive, never held whole.
 *
 * - The gate is the route file's, run before this (server/bff/gate.ts with the registry entry): a
 *   visitor without a session goes to the sign-in page and comes back, and a session without a
 *   regulatory role is answered as if the route did not exist (404), as the admin tools answer a
 *   tenant role. The pipeline checks the role again once it reads tokens.
 * - The document's record is read first (`GET /v1/pipeline/documents/{id}`), so the content type
 *   and the file name come from the stored metadata, and an id the pipeline does not hold is a
 *   plain 404; the answer's headers are built from it before the bytes are asked for; then the
 *   bytes (`GET .../raw`), whose time limit covers only the wait for the response to start, whose
 *   body stops when the browser goes away, and which are cancelled if the answer cannot be built.
 * - What is sent on: the stored content type when it is one the pipeline takes (a PDF, an HTML
 *   page) and `application/octet-stream` otherwise; `Content-Disposition` inline for those types
 *   and as an attachment otherwise, named by the document's id (ASCII only) with its title in
 *   `filename*` (well formed, at most 100 characters by code point); `nosniff`; `Cache-Control:
 *   private, no-store`, since the bytes are behind a session; an HTML page sandboxed with nothing
 *   loaded from anywhere (`sandbox; default-src 'none'`), so a regulator's page runs no script
 *   under this site's origin and reaches no other site. The app's static headers (next.config.ts)
 *   still apply on top: `X-Frame-Options: DENY`, so no page frames the bytes, and the app's
 *   referrer policy, which replaces any a handler sets.
 * - The pipeline's refusals are said plainly: an unknown document (404), the role (403), a file
 *   missing or altered in the raw store (502), the raw store away (503).
 */
type Client = ReturnType<typeof pipelineClient>;

/** The media types the pipeline stores, with the extension a saved file gets. */
const SERVED_TYPES: Readonly<Record<string, string>> = {
  "application/pdf": "pdf",
  "text/html": "html",
  "application/xhtml+xml": "xhtml",
};

const HTML_TYPES = new Set(["text/html", "application/xhtml+xml"]);

export const RAW_CONTENT_SECURITY_POLICY = "sandbox; default-src 'none'";

export interface RawDocumentDeps {
  fetchImpl?: FetchImpl;
}

/** The base media type of a stored content type, lower-cased. */
function baseType(contentType: string): string {
  return (contentType.split(";")[0] ?? "").trim().toLowerCase();
}

/**
 * The content type sent on: the stored one when its base is served (with its charset when it
 * names a plain one), `application/octet-stream` otherwise.
 */
export function servedContentType(stored: string): string {
  const base = baseType(stored);
  if (!(base in SERVED_TYPES)) return "application/octet-stream";
  const charset = /;\s*charset=("?)([A-Za-z0-9_.:-]{1,40})\1\s*(?:;|$)/i.exec(stored)?.[2];
  return charset === undefined ? base : `${base}; charset=${charset}`;
}

/** The most characters (code points) of a title a file name keeps. */
export const FILE_NAME_MAX_CHARS = 100;

/**
 * The title or reference as a file name: well formed (a lone surrogate becomes U+FFFD), no
 * control character, separator or quote, and at most 100 characters counted by code point, so a
 * cut never splits a character outside the Basic Multilingual Plane into a lone surrogate, which
 * `encodeURIComponent` refuses.
 */
export function cleanName(text: string): string {
  const cleaned = text
    .toWellFormed()
    .normalize("NFC")
    .replace(/[\u0000-\u001f\u007f"\\/:*?<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return Array.from(cleaned).slice(0, FILE_NAME_MAX_CHARS).join("").trim();
}

/** RFC 8187: UTF-8, every byte outside attr-char percent-encoded; the text is well formed. */
function extValue(text: string): string {
  return encodeURIComponent(text).replace(
    /['()*]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

/**
 * `inline` for a served type, `attachment` otherwise; the plain name is the document's id with
 * its extension, and `filename*` carries the title (or the reference) when there is one.
 */
export function contentDisposition(document: StoredDocument): string {
  const extension = SERVED_TYPES[baseType(document.contentType)] ?? "bin";
  const disposition = extension === "bin" ? "attachment" : "inline";
  const plain = `${document.documentId}.${extension}`;
  const titled = cleanName(document.title) || cleanName(document.externalRef);
  return titled === ""
    ? `${disposition}; filename="${plain}"`
    : `${disposition}; filename="${plain}"; filename*=UTF-8''${extValue(`${titled}.${extension}`)}`;
}

/** The headers of the bytes sent on. */
export function rawHeaders(document: StoredDocument, contentLength: string | null): Headers {
  const headers = new Headers({
    "content-type": servedContentType(document.contentType),
    "content-disposition": contentDisposition(document),
    "x-content-type-options": "nosniff",
    "cache-control": "private, no-store",
  });
  if (HTML_TYPES.has(baseType(document.contentType))) {
    headers.set("content-security-policy", RAW_CONTENT_SECURITY_POLICY);
  }
  if (contentLength !== null && /^\d+$/.test(contentLength)) {
    headers.set("content-length", contentLength);
  }
  return headers;
}

/** A pipeline refusal said plainly. */
function refused(error: ApiError): Response {
  switch (error.status) {
    case 404:
      return apiErrorResponse(error, {
        title: t("rawDocument.notFound"),
        detail: t("rawDocument.notFoundDetail"),
      });
    case 403:
      return apiErrorResponse(error, {
        title: t("rawDocument.forbidden"),
        detail: t("rawDocument.forbiddenDetail"),
      });
    case 502:
      return apiErrorResponse(error, {
        title: t("rawDocument.unreadable"),
        detail: t("rawDocument.unreadableDetail"),
      });
    case 503:
      return apiErrorResponse(error, {
        title: t("rawDocument.storeUnavailable"),
        detail: t("rawDocument.storeUnavailableDetail"),
      });
    default:
      return apiErrorResponse(error);
  }
}

function notFound(): Response {
  return problemResponse({
    slug: "web-not-found",
    status: 404,
    title: t("rawDocument.notFound"),
    detail: t("rawDocument.notFoundDetail"),
  });
}

function bytesClient(deps: RawDocumentDeps): Client {
  const env = getEnv();
  return createServiceClient<pipeline.paths>({
    service: "pipeline",
    baseUrl: serviceUrl("pipeline", env),
    timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
    timeoutScope: "response-start",
    fetchImpl: deps.fetchImpl,
    headers: {},
  });
}

/**
 * The handler's answer to a request for a document's bytes, for the session the route's gate let
 * through (`_session`: the gate checked its roles; the pipeline names no reader).
 */
export async function rawDocumentResponse(
  request: Request,
  documentId: string,
  _session: SessionClaims,
  deps: RawDocumentDeps = {},
): Promise<Response> {
  if (!isHexUuid(documentId)) return notFound();
  const id = documentId.toLowerCase();
  const record = await call(
    pipelineClient({ fetchImpl: deps.fetchImpl }).GET("/v1/pipeline/documents/{document_id}", {
      params: { path: { document_id: id } },
      cache: "no-store",
    }),
  );
  const document = mapBody(record, storedDocumentFromDto);
  if (!document.ok) return refused(document.error);
  // The headers come from the record alone, so they are built before the bytes are asked for: a
  // record they cannot be built from fails here, with no stream open. The raw store serves
  // exactly the stored bytes (checked against the record's digest), so their length is the
  // record's size.
  const headers = rawHeaders(document.value, String(document.value.size));
  const bytes = await call(
    bytesClient(deps).GET("/v1/pipeline/documents/{document_id}/raw", {
      params: { path: { document_id: id } },
      parseAs: "stream",
      cache: "no-store",
      signal: request.signal,
    }),
  );
  if (!bytes.ok) return refused(bytes.error);
  return forwardBytes(bytes.value as ReadableStream<Uint8Array> | null | undefined, headers);
}

/**
 * The stored bytes sent on under their headers. Anything that fails once the raw store's body is
 * open cancels that body before the error goes on, so the pipeline's response is never left
 * streaming into nothing.
 */
export function forwardBytes(
  body: ReadableStream<Uint8Array> | null | undefined,
  headers: HeadersInit,
): Response {
  try {
    return new Response(body ?? null, { status: 200, headers });
  } catch (error) {
    void body?.cancel(error).catch(() => undefined);
    throw error;
  }
}
