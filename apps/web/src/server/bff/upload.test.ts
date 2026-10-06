// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { fakeFetch, problemResponse, refusingFetch } from "@/test/fake-fetch";
import { ACTOR_ID, UPLOAD_SOURCE_KEY, documentDto } from "@/test/pipeline-fixture";
import { WRITE_TOKEN_HEADER } from "../api/client";
import { resetEnvCache } from "../env";
import {
  FORM_ALLOWANCE,
  UPLOAD_TYPES,
  checkUploadFields,
  documentIdOf,
  megabytes,
  uploadResponse,
} from "./upload";

const BOUNDARY = "----ExampleBrowserBoundary42";
const URL_BASE = `http://localhost:3000/api-bff/pipeline/sources/${UPLOAD_SOURCE_KEY}/uploads`;
const UPLOAD_PATH = `/v1/pipeline/sources/${UPLOAD_SOURCE_KEY}/uploads`;
const PDF = Buffer.from("%PDF-1.4\nExample statute text\n%%EOF\n");
const SHA = createHash("sha256").update(PDF).digest("hex");
const REASON = "Example reason for the upload";

function claims(
  roles: SessionClaims["roles"],
  tenantKind: SessionClaims["tenantKind"] = "internal",
): SessionClaims {
  return {
    userId: ACTOR_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind,
    roles,
    displayName: "Example admin",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
}

const ADMIN = claims(["admin"]);

function multipart(
  fields: Readonly<Record<string, string>>,
  file: { bytes: Buffer; type: string } | null = { bytes: PDF, type: "application/pdf" },
): Buffer {
  const parts: Buffer[] = [];
  for (const [name, value] of Object.entries(fields)) {
    parts.push(
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`,
      ),
    );
  }
  if (file !== null) {
    parts.push(
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="example.pdf"\r\n` +
          `Content-Type: ${file.type}\r\n\r\n`,
      ),
      file.bytes,
      Buffer.from("\r\n"),
    );
  }
  parts.push(Buffer.from(`--${BOUNDARY}--\r\n`));
  return Buffer.concat(parts);
}

function request(body: Buffer, headers: Record<string, string> = {}, url = URL_BASE): Request {
  return new Request(url, {
    method: "POST",
    headers: {
      host: "localhost:3000",
      "sec-fetch-site": "same-origin",
      "content-type": `multipart/form-data; boundary=${BOUNDARY}`,
      ...headers,
    },
    body,
    duplex: "half",
  } as RequestInit);
}

async function problemOf(response: Response): Promise<Record<string, unknown>> {
  expect(response.headers.get("content-type")).toContain("application/problem+json");
  return (await response.json()) as Record<string, unknown>;
}

beforeEach(() => {
  vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("uploadResponse: who may upload", () => {
  it("refuses another site, no session, a tenant role and an analyst before reading the body", async () => {
    const fake = fakeFetch([]);
    const deps = { fetchImpl: fake.fetchImpl };
    const body = multipart({ reason: REASON });
    const cross = await uploadResponse(
      request(body, { "sec-fetch-site": "cross-site" }),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(cross.status).toBe(403);
    expect((await problemOf(cross)).type).toBe(
      "urn:compliancewatch:problem:web-cross-origin-request",
    );
    expect((await uploadResponse(request(body), UPLOAD_SOURCE_KEY, null, deps)).status).toBe(401);
    const owner = claims(["owner"], "business");
    expect((await uploadResponse(request(body), UPLOAD_SOURCE_KEY, owner, deps)).status).toBe(404);
    const analyst = await uploadResponse(
      request(body),
      UPLOAD_SOURCE_KEY,
      claims(["analyst"]),
      deps,
    );
    expect(analyst.status).toBe(403);
    expect((await problemOf(analyst)).type).toBe(
      "urn:compliancewatch:problem:web-admin-role-required",
    );
    expect(fake.requests).toHaveLength(0);
  });

  it("says the token is missing, and refuses a bad key, a body that is not a form, and a long one", async () => {
    const fake = fakeFetch([]);
    const deps = { fetchImpl: fake.fetchImpl };
    const body = multipart({ reason: REASON });
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "");
    resetEnvCache();
    const missing = await uploadResponse(request(body), UPLOAD_SOURCE_KEY, ADMIN, deps);
    expect(missing.status).toBe(503);
    expect((await problemOf(missing)).detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
    resetEnvCache();
    expect((await uploadResponse(request(body), "Not-A-Key", ADMIN, deps)).status).toBe(404);
    const json = await uploadResponse(
      request(Buffer.from("{}"), { "content-type": "application/json" }),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(json.status).toBe(415);
    const long = await uploadResponse(
      request(body, { "content-length": String(25_000_000 + FORM_ALLOWANCE + 1) }),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(long.status).toBe(413);
    expect((await problemOf(long)).detail).toContain("25 MB");
    expect(fake.requests).toHaveLength(0);
  });
});

describe("uploadResponse: the form", () => {
  it("names each field the pipeline would refuse, and refuses a file of another type", async () => {
    const fake = fakeFetch([]);
    const deps = { fetchImpl: fake.fetchImpl };
    const invalid = await uploadResponse(
      request(
        multipart({
          reason: "short",
          published_on: "2000-13-40",
          document_type: "memo",
          external_ref: "x".repeat(201),
        }),
      ),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(invalid.status).toBe(422);
    const problem = await problemOf(invalid);
    expect((problem.errors as { loc: string[] }[]).map((issue) => issue.loc[1])).toEqual([
      "reason",
      "external_ref",
      "published_on",
      "document_type",
    ]);
    const text = await uploadResponse(
      request(multipart({ reason: REASON }, { bytes: Buffer.from("x"), type: "text/plain" })),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(text.status).toBe(415);
    expect((await problemOf(text)).detail).toContain("text/plain");
    const noFile = await uploadResponse(
      request(multipart({ reason: REASON }, null)),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      deps,
    );
    expect(noFile.status).toBe(400);
    expect(fake.requests).toHaveLength(0);
  });

  it("checks the fields as the pipeline does", () => {
    expect(
      checkUploadFields(
        new Map([
          ["reason", `  ${REASON}  `],
          ["title", " Example title "],
          ["published_on", "2000-01-01"],
          ["document_type", "statute"],
        ]),
      ),
    ).toEqual({
      ok: true,
      fields: {
        reason: REASON,
        title: "Example title",
        externalRef: "",
        publishedOn: "2000-01-01",
        documentType: "statute",
      },
    });
    const long = checkUploadFields(
      new Map([
        ["reason", "x".repeat(2001)],
        ["title", "x".repeat(2001)],
      ]),
    );
    expect(long.ok).toBe(false);
  });
});

describe("uploadResponse: forwarding", () => {
  it("streams a new form to the pipeline: the session's actor, the checked fields, the same bytes", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: UPLOAD_PATH,
        status: 202,
        body: {
          document: documentDto({ source_key: UPLOAD_SOURCE_KEY, doc_type: "statute" }),
          duplicate: false,
          workflow_id: "pipeline-upload-example_statutes-1",
        },
      },
    ]);
    const response = await uploadResponse(
      request(
        multipart({
          actor_id: "00000000-0000-4000-8000-00000000dead",
          reason: REASON,
          title: "Example statute",
          published_on: "2000-01-01",
          external_ref: "",
          document_type: "statute",
        }),
      ),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      { fetchImpl: fake.fetchImpl },
    );
    expect(response.status).toBe(202);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toMatchObject({
      duplicate: false,
      workflowId: "pipeline-upload-example_statutes-1",
      document: { sourceKey: UPLOAD_SOURCE_KEY, uploaderType: "statute" },
    });
    const sent = fake.requests[0];
    expect(sent?.headers[WRITE_TOKEN_HEADER]).toBe("example-write-token");
    expect(sent?.headers["x-tenant-id"]).toBeUndefined();
    const contentType = sent?.headers["content-type"] ?? "";
    const boundary = /boundary=(\S+)$/.exec(contentType)?.[1] ?? "";
    expect(boundary).toMatch(/^cw-upload-/);
    const forwarded = String(sent?.body);
    const names = [...forwarded.matchAll(/; name="([^"]+)"/g)].map((match) => match[1]);
    expect(names).toEqual(["actor_id", "reason", "title", "published_on", "document_type", "file"]);
    expect(forwarded).toContain(`\r\n\r\n${ACTOR_ID}\r\n`);
    expect(forwarded).not.toContain("00000000-0000-4000-8000-00000000dead");
    expect(forwarded).toContain('filename="document.pdf"\r\nContent-Type: application/pdf\r\n\r\n');
    expect(forwarded).toContain(`${PDF.toString("latin1")}\r\n--${boundary}--\r\n`);
  });

  it("says a document was stored without its ingest, with the id its bytes get", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: UPLOAD_PATH,
        status: 503,
        problem: {
          type: "urn:compliancewatch:problem:pipeline-ingest-unavailable",
          title: "The ingest could not be started",
          detail: "Temporal at localhost:7233 did not start the ingest",
        },
      },
    ]);
    const response = await uploadResponse(
      request(multipart({ reason: REASON })),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      {
        fetchImpl: fake.fetchImpl,
      },
    );
    expect(response.status).toBe(503);
    const problem = await problemOf(response);
    expect(problem).toMatchObject({
      type: "urn:compliancewatch:problem:pipeline-ingest-unavailable",
      title: "Stored, but its ingest did not start",
      document_id: documentIdOf(SHA),
    });
    expect(typeof problem.correlation_id).toBe("string");
  });

  it("words the pipeline's refusals plainly and passes the token's on with the variable", async () => {
    const answers = [
      {
        status: 413,
        slug: "pipeline-upload-too-large",
        title: "The file is larger than the pipeline takes",
      },
      {
        status: 415,
        slug: "pipeline-upload-unsupported",
        title: "Only a PDF or an HTML page can be uploaded",
      },
      { status: 404, slug: "pipeline-source-not-found", title: "No source has this key" },
      {
        status: 401,
        slug: "pipeline-write-token-invalid",
        title: "The pipeline refused the write token",
      },
      { status: 409, slug: "example-other", title: "Test problem 409" },
    ];
    for (const answer of answers) {
      const fake = fakeFetch(() =>
        problemResponse(answer.status, { type: `urn:compliancewatch:problem:${answer.slug}` }),
      );
      const response = await uploadResponse(
        request(multipart({ reason: REASON })),
        UPLOAD_SOURCE_KEY,
        ADMIN,
        {
          fetchImpl: fake.fetchImpl,
        },
      );
      expect(response.status, answer.slug).toBe(answer.status);
      expect((await problemOf(response)).title, answer.slug).toBe(answer.title);
    }
    const refusing = refusingFetch();
    const away = await uploadResponse(
      request(multipart({ reason: REASON })),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      {
        fetchImpl: refusing.fetchImpl,
      },
    );
    expect(away.status).toBe(502);
    expect((await problemOf(away)).title).toBe("The pipeline could not be reached");
  });

  it("stops a file past the limit as it streams, and a part sent after the file", async () => {
    vi.stubEnv("CW_WEB_PIPELINE_UPLOAD_MAX_BYTES", "10");
    resetEnvCache();
    const fake = fakeFetch([{ method: "POST", path: UPLOAD_PATH, status: 202, body: {} }]);
    const big = await uploadResponse(
      request(multipart({ reason: REASON })),
      UPLOAD_SOURCE_KEY,
      ADMIN,
      {
        fetchImpl: fake.fetchImpl,
      },
    );
    expect(big.status).toBe(413);
    vi.stubEnv("CW_WEB_PIPELINE_UPLOAD_MAX_BYTES", "1000");
    resetEnvCache();
    const sneaky = Buffer.concat([
      multipart({ reason: REASON }).subarray(0, -`--${BOUNDARY}--\r\n`.length),
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="actor_id"\r\n\r\nx\r\n--${BOUNDARY}--\r\n`,
      ),
    ]);
    const after = await uploadResponse(request(sneaky), UPLOAD_SOURCE_KEY, ADMIN, {
      fetchImpl: fake.fetchImpl,
    });
    expect(after.status).toBe(400);
  });
});

describe("the limits match the pipeline's", () => {
  const SERVICE = resolve(__dirname, "../../../../../services/pipeline/src/pipeline");

  it("takes the pipeline's upload limit, its ceiling and its allowance for the fields", () => {
    const settings = readFileSync(resolve(SERVICE, "settings.py"), "utf8");
    expect(settings).toMatch(
      /pipeline_upload_max_bytes: int = Field\(default=25_000_000, ge=1, le=100_000_000\)/,
    );
    const route = readFileSync(resolve(SERVICE, "api/uploads.py"), "utf8");
    expect(route).toMatch(/FORM_ALLOWANCE: Final = 64 \* 1024/);
    expect(FORM_ALLOWANCE).toBe(64 * 1024);
    expect(megabytes(25_000_000)).toBe("25 MB");
  });

  it("takes the file types the pipeline stores", () => {
    const uploads = readFileSync(resolve(SERVICE, "application/uploads.py"), "utf8");
    const declared = [...uploads.matchAll(/^(?:PDF|HTML|XHTML): Final = "([^"]+)"$/gm)].map(
      (match) => match[1],
    );
    expect(declared.sort()).toEqual(Object.keys(UPLOAD_TYPES).sort());
  });
});
