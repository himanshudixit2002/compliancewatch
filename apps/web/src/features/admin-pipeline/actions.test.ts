// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, refusingFetch } from "@/test/fake-fetch";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  EVENT_ID,
  TASK_ID,
  documentDetailDto,
  outboxEventDto,
  retryDto,
  taskDto,
} from "@/test/pipeline-fixture";
import { dismissTask, requeueEvent, resolveTask, retryDocument } from "./actions";
import { DISMISS_FIELDS, REQUEUE_FIELDS, RESOLVE_FIELDS, RETRY_FIELDS } from "./ui/pipeline-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const REASON = "Example reason of enough length";
const RETRY_KEY = "00000000-0000-4000-8000-0000000000a1";

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: ACTOR_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind: "internal",
    roles,
    displayName: "Example admin",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(values)) data.set(name, value);
  return data;
}

function retryForm(overrides: Record<string, string> = {}): FormData {
  return form({
    [RETRY_FIELDS.stage]: "parse",
    [RETRY_FIELDS.reason]: REASON,
    [IDEMPOTENCY_KEY_FIELD]: RETRY_KEY,
    ...overrides,
  });
}

function accepted(started: boolean, replayed = false, reclassified = false): Response {
  return jsonResponse(
    202,
    {
      retry: retryDto({ attempt: 2, doc_type: reclassified ? "circular" : null }),
      document: documentDetailDto(),
      started,
      reclassified,
      workflow_id: `pipeline-retry-${DOCUMENT_ID}-2`,
    },
    replayed ? { "Idempotent-Replayed": "true" } : {},
  );
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new Error("not found");
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("retryDocument", () => {
  it("sends the stage, type and reason with the form's key, and says what started", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch(() => accepted(true, false, true));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await retryDocument(
      DOCUMENT_ID,
      IDLE,
      retryForm({ [RETRY_FIELDS.stage]: "classify", [RETRY_FIELDS.docType]: "circular" }),
    );
    expect(state.status === "ok" && state.value?.message).toBe(
      `Attempt 2 from Parse recorded. Its ingest started (workflow pipeline-retry-${DOCUMENT_ID}-2). The document is read as a Circular from now on.`,
    );
    expect(fake.requests[0]?.headers["idempotency-key"]).toBe(RETRY_KEY);
    expect(fake.requests[0]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      stage: "classify",
      doc_type: "circular",
    });
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      `/admin/pipeline/documents/${DOCUMENT_ID}`,
      "/admin/pipeline",
    ]);
  });

  it("says a replayed request recorded nothing twice", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal("fetch", fakeFetch(() => accepted(false, true)).fetchImpl);
    const state = await retryDocument(DOCUMENT_ID, IDLE, retryForm());
    expect(state.status === "ok" && state.value?.message).toMatch(
      /^This request was recorded before, as attempt 2 from Parse: nothing was recorded twice\. Its ingest had started before/,
    );
  });

  it("says each refusal plainly, and renders again when something may be recorded", async () => {
    await signedInAs(["admin"]);
    const cases: [string, number, string][] = [
      ["pipeline-ingest-running", 409, "An ingest of this document is running"],
      ["pipeline-retry-refused", 409, "A triage task holds it, or nothing is left to extract"],
      ["pipeline-retry-invalid", 422, "No rule is extracted from this type"],
      ["idempotency-key-reused", 422, "This request's key was used for another request"],
      ["idempotency-key-required", 428, "The retry was sent without its key"],
      ["idempotency-request-in-flight", 409, "The same request is still being handled"],
      ["pipeline-ingest-unavailable", 503, "Temporal did not answer: send the same request again"],
      ["pipeline-document-not-found", 404, "The pipeline holds no stored document under this id"],
    ];
    for (const [slug, status, title] of cases) {
      vi.mocked(revalidatePath).mockClear();
      vi.stubGlobal(
        "fetch",
        fakeFetch(() =>
          problemResponse(status, {
            type: `urn:compliancewatch:problem:${slug}`,
            detail: "Example detail from the pipeline",
          }),
        ).fetchImpl,
      );
      const state = await retryDocument(DOCUMENT_ID, IDLE, retryForm());
      expect(state.status === "error" && state.problem?.title, slug).toBe(title);
      expect(vi.mocked(revalidatePath).mock.calls.length > 0, slug).toBe(
        slug === "pipeline-ingest-unavailable",
      );
      if (slug === "pipeline-retry-refused" && state.status === "error") {
        expect(state.problem?.detail).toBe("Example detail from the pipeline");
      }
    }
    vi.stubGlobal("fetch", refusingFetch().fetchImpl);
    const lost = await retryDocument(DOCUMENT_ID, IDLE, retryForm());
    expect(lost.status === "error" && lost.problem?.type).toBe(
      "urn:compliancewatch:problem:web-network",
    );
  });

  it("refuses an analyst, a bad id and a form out of shape before any request", async () => {
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await signedInAs(["analyst"]);
    expect(await retryDocument(DOCUMENT_ID, IDLE, retryForm())).toMatchObject({
      status: "error",
      formErrors: ["Only an admin retries, requeues or resolves"],
    });
    await signedInAs(["admin"]);
    expect((await retryDocument("nope", IDLE, retryForm())).status).toBe("error");
    expect(
      await retryDocument(DOCUMENT_ID, IDLE, retryForm({ [RETRY_FIELDS.stage]: "fetch" })),
    ).toMatchObject({
      status: "error",
      fieldErrors: { stage: [expect.any(String)] },
    });
    expect(fake.requests).toHaveLength(0);
  });
});

describe("requeueEvent", () => {
  it("requeues a dead row with the reason, and says when a row was not dead", async () => {
    await signedInAs(["admin"]);
    const answers = [
      { event: outboxEventDto({ status: "pending" }), requeued: true },
      { event: outboxEventDto({ status: "published" }), requeued: false },
    ];
    const fake = fakeFetch(() => jsonResponse(200, answers.shift()));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const values = { [REQUEUE_FIELDS.eventId]: EVENT_ID, [REQUEUE_FIELDS.reason]: REASON };
    const done = await requeueEvent(IDLE, form(values));
    expect(done.status === "ok" && done.value?.message).toMatch(
      /^Back to pending: the relay sends this document\.parsed row/,
    );
    const same = await requeueEvent(IDLE, form(values));
    expect(same.status === "ok" && same.value?.message).toBe(
      "The row was not dead (published): nothing changed.",
    );
    expect(fake.requests[0]?.pathname).toBe(`/v1/pipeline/outbox/${EVENT_ID}/requeue`);
    expect(fake.requests[0]?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON });
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/pipeline",
      "/admin/pipeline",
    ]);
  });

  it("says an unknown row plainly and refuses what is out of shape", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch(() =>
        problemResponse(404, {
          type: "urn:compliancewatch:problem:pipeline-outbox-event-not-found",
        }),
      ).fetchImpl,
    );
    const unknown = await requeueEvent(
      IDLE,
      form({ [REQUEUE_FIELDS.eventId]: EVENT_ID, [REQUEUE_FIELDS.reason]: REASON }),
    );
    expect(unknown.status === "error" && unknown.problem?.title).toBe(
      "The outbox holds no such row",
    );
    expect(
      (
        await requeueEvent(
          IDLE,
          form({ [REQUEUE_FIELDS.eventId]: "x", [REQUEUE_FIELDS.reason]: REASON }),
        )
      ).status,
    ).toBe("error");
    expect(
      await requeueEvent(
        IDLE,
        form({ [REQUEUE_FIELDS.eventId]: EVENT_ID, [REQUEUE_FIELDS.reason]: "short" }),
      ),
    ).toMatchObject({ status: "error", fieldErrors: { reason: [expect.any(String)] } });
    await signedInAs(["reviewer"]);
    expect((await requeueEvent(IDLE, form({}))).status).toBe("error");
  });
});

describe("resolveTask and dismissTask", () => {
  it("resolves a manual parse with its transcript and says the ingest started", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch(() =>
      jsonResponse(200, {
        task: taskDto({ status: "resolved" }),
        started: true,
        workflow_id: "pipeline-manual-parse-1",
      }),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await resolveTask(
      TASK_ID,
      "manual_parse",
      IDLE,
      form({
        [RESOLVE_FIELDS.title]: "Example title",
        [RESOLVE_FIELDS.transcript]: "# Example heading\n\n1. Example text.",
        [RESOLVE_FIELDS.reason]: REASON,
      }),
    );
    expect(state.status === "ok" && state.value?.message).toBe(
      "Resolved: its ingest started (workflow pipeline-manual-parse-1).",
    );
    expect(fake.requests[0]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      transcript: {
        title: "Example title",
        blocks: [
          { type: "heading", text: "Example heading" },
          { type: "paragraph", number: "1.", text: "Example text." },
        ],
      },
    });
  });

  it("says a resolution sent again is done, and an irrelevant triage starts nothing", async () => {
    await signedInAs(["admin"]);
    const answers = [
      {
        task: taskDto({ kind: "triage", status: "resolved" }),
        started: false,
        workflow_id: "pipeline-triage-1",
      },
      { task: taskDto({ kind: "triage", status: "resolved" }), started: false, workflow_id: "" },
    ];
    const fake = fakeFetch(() => jsonResponse(200, answers.shift()));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const relevant = form({
      [RESOLVE_FIELDS.relevance]: "relevant",
      [RESOLVE_FIELDS.docType]: "circular",
      [RESOLVE_FIELDS.reason]: REASON,
    });
    const replay = await resolveTask(TASK_ID, "triage", IDLE, relevant);
    expect(replay.status === "ok" && replay.value?.message).toMatch(
      /^Resolved: this resolution was recorded before/,
    );
    const aside = await resolveTask(
      TASK_ID,
      "triage",
      IDLE,
      form({ [RESOLVE_FIELDS.relevance]: "irrelevant", [RESOLVE_FIELDS.reason]: REASON }),
    );
    expect(aside.status === "ok" && aside.value?.message).toMatch(
      /^Resolved: the document is set aside/,
    );
    expect(fake.requests[0]?.body).toEqual({
      actor_id: ACTOR_ID,
      reason: REASON,
      triage: { relevance: "relevant", doc_type: "circular" },
    });
  });

  it("says a closed task, Temporal away, and refuses what is out of shape", async () => {
    await signedInAs(["admin"]);
    const valid = form({
      [RESOLVE_FIELDS.relevance]: "irrelevant",
      [RESOLVE_FIELDS.reason]: REASON,
    });
    vi.stubGlobal(
      "fetch",
      fakeFetch(() =>
        problemResponse(409, { type: "urn:compliancewatch:problem:pipeline-task-closed" }),
      ).fetchImpl,
    );
    const closed = await resolveTask(TASK_ID, "triage", IDLE, valid);
    expect(closed.status === "error" && closed.problem?.title).toBe("The task is closed already");
    vi.stubGlobal(
      "fetch",
      fakeFetch(() =>
        problemResponse(503, { type: "urn:compliancewatch:problem:pipeline-ingest-unavailable" }),
      ).fetchImpl,
    );
    vi.mocked(revalidatePath).mockClear();
    const away = await resolveTask(TASK_ID, "triage", IDLE, valid);
    expect(away.status === "error" && away.problem?.title).toBe(
      "Temporal did not answer: send the same request again",
    );
    expect(vi.mocked(revalidatePath)).toHaveBeenCalled();
    expect((await resolveTask("nope", "triage", IDLE, valid)).status).toBe("error");
    expect(
      await resolveTask(TASK_ID, "triage", IDLE, form({ [RESOLVE_FIELDS.reason]: REASON })),
    ).toMatchObject({ status: "error", fieldErrors: { relevance: [expect.any(String)] } });
    await signedInAs(["analyst"]);
    expect((await resolveTask(TASK_ID, "triage", IDLE, valid)).status).toBe("error");
  });

  it("dismisses a task with the reason and says what becomes of its document", async () => {
    await signedInAs(["admin"]);
    const answers = [
      taskDto({ status: "dismissed" }),
      taskDto({ kind: "triage", status: "dismissed" }),
    ];
    const fake = fakeFetch(() => jsonResponse(200, answers.shift()));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const reason = form({ [DISMISS_FIELDS.reason]: REASON });
    const manual = await dismissTask(TASK_ID, IDLE, reason);
    expect(manual.status === "ok" && manual.value?.message).toMatch(/unread by any parser/);
    const triage = await dismissTask(TASK_ID, IDLE, reason);
    expect(triage.status === "ok" && triage.value?.message).toMatch(/held for triage/);
    expect(fake.requests[0]?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON });
    expect((await dismissTask(TASK_ID, IDLE, form({ [DISMISS_FIELDS.reason]: "x" }))).status).toBe(
      "error",
    );
    expect((await dismissTask("nope", IDLE, reason)).status).toBe("error");
    vi.stubGlobal(
      "fetch",
      fakeFetch(() =>
        problemResponse(404, { type: "urn:compliancewatch:problem:pipeline-task-not-found" }),
      ).fetchImpl,
    );
    const missing = await dismissTask(TASK_ID, IDLE, reason);
    expect(missing.status === "error" && missing.problem?.title).toBe(
      "The pipeline holds no such task",
    );
    await signedInAs(["analyst"]);
    expect((await dismissTask(TASK_ID, IDLE, reason)).status).toBe("error");
  });
});
