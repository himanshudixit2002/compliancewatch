import { createHash, randomBytes, randomInt, randomUUID } from "node:crypto";
import { expect, serviceUrl } from "./fixtures";

/**
 * Reads of the pipeline the source and pipeline specs compare the pages with, straight from the
 * service the stack runs (`make web-stack` starts it on the memory store with its built-in sources,
 * crawling off and no Temporal to start an ingest on). Every write a spec checks goes through the
 * web app as a signed-in admin of the fake sign-in. The writes here only stage what a spec acts on,
 * through the pipeline's routes with the shared write token (as `stageReview` stages the review
 * queues): a synthetic upload-only source of its own for each run, named `example_<digits>`, and
 * synthetic PDF bytes uploaded to it, which the stack stores and records though their ingest does
 * not start. No staged source lists anything, so nothing here reads a regulator's site.
 */
export interface SourceRow {
  key: string;
  name: string;
  adapter_type: string;
  listable: boolean;
  paused: boolean;
  enabled: boolean;
  cadence_seconds: number;
  status: string;
  document_count: number;
}

/**
 * The prefix of a source a spec staged (`example_<nine digits>`): the specs run in parallel and
 * stage their own, so a page of every source holds more than one test read before it rendered,
 * and a staged source's name may change under another test.
 */
export const STAGED_SOURCE_PREFIX = "example_";

export interface DocumentRow {
  document_id: string;
  title: string;
  status: string;
  source_key: string;
}

const WRITE_TOKEN = () => process.env.CW_WEB_RULEBOOK_WRITE_TOKEN?.trim() || "local-write-token";

/** An actor id for the staging writes: no person, a fixed synthetic id. */
const STAGING_ACTOR = "00000000-0000-4000-8000-00000000e2e0";

export async function pipelineGet<T>(path: string): Promise<T> {
  const response = await fetch(`${serviceUrl("pipeline")}${path}`);
  expect(response.status, `GET ${path} on the pipeline`).toBe(200);
  return (await response.json()) as T;
}

export async function sources(): Promise<SourceRow[]> {
  return (await pipelineGet<{ items: SourceRow[] }>("/v1/pipeline/sources")).items;
}

/** The pipeline's id for bytes of this SHA-256: its first 32 hex digits as a UUID. */
export function documentIdOf(sha256: string): string {
  const hex = sha256.slice(0, 32);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** A synthetic file to upload: its bytes, its type and name, and the id the pipeline gives it. */
export interface SyntheticFile {
  bytes: Buffer;
  sha256: string;
  documentId: string;
  mimeType: string;
  name: string;
}

function syntheticFile(bytes: Buffer, mimeType: string, name: string): SyntheticFile {
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  return { bytes, sha256, documentId: documentIdOf(sha256), mimeType, name };
}

/** A small synthetic PDF, different every time: the pipeline checks its leading `%PDF-`. */
export function syntheticPdf(label: string): SyntheticFile {
  const bytes = Buffer.from(
    `%PDF-1.4\n% Example statute for the end-to-end suite: ${label} ${randomBytes(8).toString("hex")}\n%%EOF\n`,
  );
  return syntheticFile(bytes, "application/pdf", "example.pdf");
}

/**
 * A small synthetic HTML page, different every time, titled `title`, with a script that renames
 * it and an image from a host that never resolves (`.invalid`): served sandboxed, the script does
 * not run and the image is never asked for.
 */
export function syntheticHtml(title: string): SyntheticFile {
  const bytes = Buffer.from(
    `<!doctype html><html lang="en"><head><title>${title}</title></head><body>` +
      `<p>Example page for the end-to-end suite ${randomBytes(8).toString("hex")}</p>` +
      `<img src="https://example.invalid/example.png" alt="">` +
      `<script>document.title = "Example script ran";</script></body></html>\n`,
  );
  return syntheticFile(bytes, "text/html", "example.html");
}

/** A synthetic upload-only source of this run's own: no site, nothing listed, statutes. */
export async function stageUploadSource(): Promise<SourceRow> {
  const key = `${STAGED_SOURCE_PREFIX}${randomInt(100_000_000, 999_999_999)}`;
  const response = await fetch(`${serviceUrl("pipeline")}/v1/pipeline/sources`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-cw-write-token": WRITE_TOKEN() },
    body: JSON.stringify({
      actor_id: STAGING_ACTOR,
      reason: "Example source staged by the end-to-end suite",
      key,
      name: `Example statutes ${key.slice(-4)}`,
      adapter_type: "upload",
      parameters: { document_type: "statute", regulator: "Example regulator" },
      cadence_seconds: 86_400,
    }),
  });
  expect(response.status, `POST a staged source: ${await response.clone().text()}`).toBe(201);
  return (await response.json()) as SourceRow;
}

/**
 * Another admin's change of a staged source while a page shows it, straight through the
 * pipeline's route with the write token. Only a source a spec staged is ever changed.
 */
export async function editStagedSource(
  key: string,
  change: Readonly<Record<string, unknown>>,
): Promise<SourceRow> {
  if (!key.startsWith(STAGED_SOURCE_PREFIX)) throw new Error(`${key} is not a staged source`);
  const response = await fetch(`${serviceUrl("pipeline")}/v1/pipeline/sources/${key}`, {
    method: "PATCH",
    headers: { "content-type": "application/json", "x-cw-write-token": WRITE_TOKEN() },
    body: JSON.stringify({
      actor_id: STAGING_ACTOR,
      reason: "Example change by another admin, staged by the end-to-end suite",
      ...change,
    }),
  });
  expect(response.status, `PATCH a staged source: ${await response.clone().text()}`).toBe(200);
  return (await response.json()) as SourceRow;
}

/**
 * Synthetic bytes (a PDF unless a file is given) uploaded to a staged source through the
 * pipeline's own route. The stack stores and records them and answers 503 (no Temporal for the
 * ingest); a stack with Temporal answers 202. Either way the document is stored.
 */
export async function stageUpload(
  key: string,
  title: string,
  file: SyntheticFile = syntheticPdf(title),
): Promise<{ documentId: string }> {
  const form = new FormData();
  form.set("actor_id", STAGING_ACTOR);
  form.set("reason", "Example document staged by the end-to-end suite");
  form.set("title", title);
  form.set("published_on", "2000-01-01");
  form.set("file", new Blob([new Uint8Array(file.bytes)], { type: file.mimeType }), file.name);
  const response = await fetch(`${serviceUrl("pipeline")}/v1/pipeline/sources/${key}/uploads`, {
    method: "POST",
    headers: { "x-cw-write-token": WRITE_TOKEN() },
    body: form,
  });
  expect([202, 503], `POST a staged upload: ${await response.clone().text()}`).toContain(
    response.status,
  );
  return { documentId: file.documentId };
}

/**
 * Whether crawling is off on the stack, asked the way cw-product check asks it: a fetch of a key
 * no source has is refused as crawling off (503 pipeline-crawl-disabled) before the pipeline looks
 * the source up; with crawling on it would be a 404, and nothing would start either. A spec that
 * fetches a built-in source asks this first and never fetches one while crawling is on.
 */
export async function crawlIsOff(): Promise<boolean> {
  const response = await fetch(
    `${serviceUrl("pipeline")}/v1/pipeline/sources/example_absent_${randomInt(1_000, 9_999)}/fetch`,
    {
      method: "POST",
      headers: { "content-type": "application/json", "x-cw-write-token": WRITE_TOKEN() },
      body: JSON.stringify({
        actor_id: STAGING_ACTOR,
        reason: "Example check that crawling is off",
      }),
    },
  );
  if (response.status !== 503) return false;
  const problem = (await response.json()) as { type?: string };
  return problem.type === "urn:compliancewatch:problem:pipeline-crawl-disabled";
}

/** A random id no document has. */
export function unknownDocumentId(): string {
  return randomUUID();
}
