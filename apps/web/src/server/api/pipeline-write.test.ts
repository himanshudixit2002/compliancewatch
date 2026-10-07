// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  EVENT_ID,
  SOURCE_KEY,
  TASK_ID,
  documentDetailDto,
  outboxEventDto,
  retryDto,
  sourceDto,
  taskDto,
} from "@/test/pipeline-fixture";
import { resetEnvCache } from "../env";
import { WRITE_TOKEN_HEADER } from "./client";
import {
  PIPELINE_WRITE_TIMEOUT_MS,
  RefusedPipelineWrites,
  explainPipelineTokenProblem,
  pipelineWriteAccess,
  pipelineWriteClient,
  pipelineWrites,
} from "./pipeline-write";
import type { ClientContext, ClientPrincipal } from "./services";

const ADMIN: ClientPrincipal = {
  userId: ACTOR_ID,
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["admin"],
};
const ANALYST: ClientPrincipal = { ...ADMIN, roles: ["analyst"] };
const REASON = "Example reason of enough length";
const KEY = "00000000-0000-4000-8000-0000000000a1";

function ctx(session: ClientPrincipal | null, fake: ReturnType<typeof fakeFetch>): ClientContext {
  return { session, fetchImpl: fake.fetchImpl };
}

beforeEach(() => {
  vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("pipelineWriteClient", () => {
  it("refuses a session without the capability and a server without the token, before a request", () => {
    const fake = fakeFetch([]);
    const analyst = pipelineWriteClient(ctx(ANALYST, fake), "admin.pipeline.control");
    expect(analyst.ok).toBe(false);
    if (!analyst.ok) {
      expect(analyst.error).toMatchObject({ kind: "forbidden", status: 403 });
      expect(analyst.error.problem?.type).toBe(
        "urn:compliancewatch:problem:web-admin-role-required",
      );
    }
    expect(pipelineWriteClient(ctx(null, fake), "admin.sources.write").ok).toBe(false);
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "");
    resetEnvCache();
    const missing = pipelineWriteClient(ctx(ADMIN, fake), "admin.sources.write");
    expect(missing.ok).toBe(false);
    if (!missing.ok) {
      expect(missing.error).toMatchObject({ kind: "unavailable", status: 503 });
      expect(missing.error.problem?.detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
      expect(missing.error.problem?.detail).not.toContain("example-write-token");
    }
    expect(pipelineWriteAccess(ctx(ADMIN, fake), "admin.sources.write").allowed).toBe(false);
    expect(fake.requests).toHaveLength(0);
  });

  it("sends the token and no tenant header, and waits longer than a read", async () => {
    vi.stubEnv("CW_WEB_REQUEST_TIMEOUT_MS", "20");
    resetEnvCache();
    let aborted: boolean | undefined;
    const fake = fakeFetch(async (_request, raw) => {
      await new Promise((resolve) => setTimeout(resolve, 60));
      aborted = raw.signal.aborted;
      return jsonResponse(200, { items: [] });
    });
    const client = pipelineWriteClient(ctx(ADMIN, fake), "admin.sources.write");
    expect(client.ok).toBe(true);
    if (!client.ok) return;
    await client.value.GET("/v1/pipeline/sources");
    expect(fake.requests[0]?.headers[WRITE_TOKEN_HEADER]).toBe("example-write-token");
    expect(fake.requests[0]?.headers["x-tenant-id"]).toBeUndefined();
    expect(aborted).toBe(false);
    expect(PIPELINE_WRITE_TIMEOUT_MS).toBeGreaterThanOrEqual(30_000);
    expect(pipelineWriteAccess(ctx(ADMIN, fake), "admin.pipeline.control")).toEqual({
      allowed: true,
    });
  });
});

describe("pipelineWrites", () => {
  it("edits a source with only the changed fields, the reason and the session's user", async () => {
    const fake = fakeFetch([
      {
        method: "PATCH",
        path: `/v1/pipeline/sources/${SOURCE_KEY}`,
        body: sourceDto({ paused: true }),
      },
    ]);
    const result = await pipelineWrites(ctx(ADMIN, fake), "admin.sources.write").editSource(
      SOURCE_KEY,
      { paused: true },
      REASON,
    );
    expect(result.ok && result.value.paused).toBe(true);
    expect(fake.requests[0]?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON, paused: true });
  });

  it("fetches a source, requeues a row and dismisses a task with the reason", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: `/v1/pipeline/sources/${SOURCE_KEY}/fetch`,
        status: 202,
        body: { run_id: "r", source_key: SOURCE_KEY, trigger: "manual", workflow_id: "w" },
      },
      {
        method: "POST",
        path: `/v1/pipeline/outbox/${EVENT_ID}/requeue`,
        body: { event: outboxEventDto({ status: "pending" }), requeued: true },
      },
      {
        method: "POST",
        path: `/v1/pipeline/tasks/${TASK_ID}/dismiss`,
        body: taskDto({ status: "dismissed", note: REASON }),
      },
    ]);
    const writes = pipelineWrites(ctx(ADMIN, fake), "admin.pipeline.control");
    expect((await writes.fetchSource(SOURCE_KEY, REASON)).ok).toBe(true);
    const requeued = await writes.requeueEvent(EVENT_ID, REASON);
    expect(requeued.ok && requeued.value.requeued).toBe(true);
    const dismissed = await writes.dismissTask(TASK_ID, REASON);
    expect(dismissed.ok && dismissed.value.status).toBe("dismissed");
    for (const request of fake.requests) {
      expect(request.body).toEqual({ actor_id: ACTOR_ID, reason: REASON });
      expect(request.headers[WRITE_TOKEN_HEADER]).toBe("example-write-token");
    }
  });

  it("retries with the form's key and says when the pipeline replayed the attempt", async () => {
    const fake = fakeFetch((request) =>
      jsonResponse(
        202,
        {
          retry: retryDto({ stage: "classify", doc_type: "circular" }),
          document: documentDetailDto(),
          started: false,
          reclassified: false,
          workflow_id: `pipeline-retry-${DOCUMENT_ID}-1`,
        },
        request.headers["idempotency-key"] === KEY ? { "Idempotent-Replayed": "true" } : {},
      ),
    );
    const writes = pipelineWrites(ctx(ADMIN, fake), "admin.pipeline.control");
    const result = await writes.retryDocument(
      DOCUMENT_ID,
      { stage: "classify", docType: "circular" },
      REASON,
      { "Idempotency-Key": KEY },
    );
    expect(result.ok && result.value.replayed).toBe(true);
    expect(result.ok && result.value.value.retry.docType).toBe("circular");
    expect(fake.requests[0]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      stage: "classify",
      doc_type: "circular",
    });
    const plain = await writes.retryDocument(
      DOCUMENT_ID,
      { stage: "parse", docType: null },
      REASON,
      {
        "Idempotency-Key": "00000000-0000-4000-8000-0000000000a2",
      },
    );
    expect(plain.ok && plain.value.replayed).toBe(false);
    expect(fake.requests[1]?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON, stage: "parse" });
  });

  it("resolves a manual parse with a transcript and a triage with a decision", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: `/v1/pipeline/tasks/${TASK_ID}/resolve`,
        body: { task: taskDto({ status: "resolved" }), started: true, workflow_id: "w" },
      },
    ]);
    const writes = pipelineWrites(ctx(ADMIN, fake), "admin.pipeline.control");
    await writes.resolveTask(
      TASK_ID,
      {
        transcript: {
          title: "Example",
          blocks: [{ type: "heading", text: "Example", page: null }],
        },
      },
      REASON,
    );
    await writes.resolveTask(TASK_ID, { triage: { relevance: "irrelevant" } }, REASON);
    expect(fake.requests[0]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      transcript: { title: "Example", blocks: [{ type: "heading", text: "Example" }] },
    });
    expect(fake.requests[1]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      triage: { relevance: "irrelevant" },
    });
  });

  it("rewords the pipeline's token refusals and passes the others on", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: `/v1/pipeline/sources/${SOURCE_KEY}/fetch`,
        status: 401,
        problem: { type: "urn:compliancewatch:problem:pipeline-write-token-invalid" },
      },
      {
        method: "POST",
        path: `/v1/pipeline/outbox/${EVENT_ID}/requeue`,
        status: 503,
        problem: { type: "urn:compliancewatch:problem:pipeline-writes-disabled" },
      },
      {
        method: "POST",
        path: `/v1/pipeline/tasks/${TASK_ID}/dismiss`,
        status: 409,
        problem: {
          type: "urn:compliancewatch:problem:pipeline-task-closed",
          title: "The task is closed",
        },
      },
    ]);
    const writes = pipelineWrites(ctx(ADMIN, fake), "admin.pipeline.control");
    const wrong = await writes.fetchSource(SOURCE_KEY, REASON);
    expect(!wrong.ok && wrong.error.message).toBe("The pipeline refused the write token");
    const off = await writes.requeueEvent(EVENT_ID, REASON);
    expect(!off.ok && off.error.problem?.detail).toContain("CW_RULEBOOK_WRITE_TOKEN");
    const closed = await writes.dismissTask(TASK_ID, REASON);
    expect(!closed.ok && closed.error.message).toBe("The task is closed");
    const retried = await writes.retryDocument(
      DOCUMENT_ID,
      { stage: "parse", docType: null },
      REASON,
      {},
    );
    expect(retried.ok).toBe(false);
    expect(explainPipelineTokenProblem({ kind: "network", requestId: "r", message: "m" })).toEqual({
      kind: "network",
      requestId: "r",
      message: "m",
    });
  });

  it("answers every write with the refusal, and no request, for an analyst", async () => {
    const fake = fakeFetch(() => problemResponse(500));
    const writes = pipelineWrites(ctx(ANALYST, fake), "admin.pipeline.control");
    expect(writes).toBeInstanceOf(RefusedPipelineWrites);
    const answers = await Promise.all([
      writes.editSource(SOURCE_KEY, {}, REASON),
      writes.fetchSource(SOURCE_KEY, REASON),
      writes.retryDocument(DOCUMENT_ID, { stage: "parse", docType: null }, REASON, {}),
      writes.requeueEvent(EVENT_ID, REASON),
      writes.resolveTask(TASK_ID, { triage: { relevance: "irrelevant" } }, REASON),
      writes.dismissTask(TASK_ID, REASON),
    ]);
    for (const answer of answers) expect(answer.ok).toBe(false);
    expect(fake.requests).toHaveLength(0);
  });
});
