// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { fakeFetch } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { documentDetailDto } from "@/test/pipeline-fixture";
import { EXAMPLE_DOCUMENT_ID, documentDto, relationCandidateDto } from "@/test/rulebook-fixture";
import { ruleDto, ruleVersionDto } from "@/test/rule-version-fixture";
import {
  EXAMPLE_CANDIDATE_TASK_ID,
  EXAMPLE_TASK_ID,
  candidateTaskDetailDto,
  queuedTaskDto,
  reviewStatsDto,
  reviewTaskDetailDto,
  reviewTaskDto,
  taskPageDto,
} from "@/test/review-task-fixture";
import { getQueuePage, getStatsPage, getWorkbench, relationsOffered, taskNow } from "./queries";

const SESSION: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b9",
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["analyst"],
};

beforeEach(() => {
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
  vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
});

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getQueuePage", () => {
  it("reads a page of tasks, the strip and the regulators side by side, with the write access", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/tasks", body: taskPageDto([queuedTaskDto()], "next") },
      { path: "/v1/rulebook/review/stats", body: reviewStatsDto() },
    ]);
    const page = await getQueuePage(
      SESSION,
      { status: "all", kind: null, regulator: null, cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(page.queue).toMatchObject({
      ok: true,
      value: {
        rows: [{ taskId: EXAMPLE_TASK_ID }],
        nextHref: "/admin/review?status=all&cursor=next",
      },
    });
    expect(page.strip).toMatchObject({ ok: true, value: { open: 3 } });
    expect(page.regulators).toEqual(["example_regulator", "example_other"]);
    expect(page.access).toEqual({ allowed: true });
    expect(fake.requests[0]?.url).toBe("http://localhost:8003/v1/rulebook/review/tasks?limit=25");
  });

  it("keeps the queue when the stats fail, and says why the access is refused", async () => {
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "false");
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/tasks", body: taskPageDto([]) },
      { path: "/v1/rulebook/review/stats", status: 500, problem: { title: "Example failure" } },
    ]);
    const page = await getQueuePage(
      SESSION,
      { status: "open", kind: "seed", regulator: "example_regulator", cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(page.queue.ok).toBe(true);
    expect(page.strip).toMatchObject({ ok: false, error: { message: "Example failure" } });
    expect(page.regulators).toEqual([]);
    expect(page.access).toMatchObject({
      allowed: false,
      title: "The web.admin_rulebook_writes flag is off",
    });
    expect(fake.requests[0]?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/tasks?limit=25&status=open&regulator=example_regulator&kind=seed",
    );
  });

  it("passes a failed queue read on", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/rulebook/review/tasks",
        status: 422,
        problem: { title: "Example cursor refused" },
      },
      { path: "/v1/rulebook/review/stats", body: reviewStatsDto() },
    ]);
    const page = await getQueuePage(
      SESSION,
      { status: "open", kind: null, regulator: null, cursor: "stale" },
      { fetchImpl: fake.fetchImpl },
    );
    expect(page.queue).toMatchObject({ ok: false, error: { message: "Example cursor refused" } });
  });
});

describe("getStatsPage", () => {
  it("reads the stats, or passes their failure on", async () => {
    expect(
      await getStatsPage({
        fetchImpl: fakeFetch([{ path: "/v1/rulebook/review/stats", body: reviewStatsDto() }])
          .fetchImpl,
      }),
    ).toMatchObject({ ok: true, value: { byStatus: { total: 8 } } });
    expect(
      await getStatsPage({
        fetchImpl: fakeFetch([
          { path: "/v1/rulebook/review/stats", status: 503, problem: { title: "Example away" } },
        ]).fetchImpl,
      }),
    ).toMatchObject({ ok: false });
  });
});

describe("getWorkbench", () => {
  it("answers null for a task the rulebook does not hold, and passes another failure on", async () => {
    const missing = fakeFetch([
      {
        path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`,
        status: 404,
        problem: { title: "Example missing" },
      },
    ]);
    expect(await getWorkbench(SESSION, EXAMPLE_TASK_ID, { fetchImpl: missing.fetchImpl })).toEqual({
      ok: true,
      value: null,
    });
    const failed = fakeFetch([
      {
        path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`,
        status: 500,
        problem: { title: "Example failure" },
      },
    ]);
    expect(
      await getWorkbench(SESSION, EXAMPLE_TASK_ID, { fetchImpl: failed.fetchImpl }),
    ).toMatchObject({
      ok: false,
    });
  });

  it("reads a seed task with its documents, stored files, the ontology and the rule's versions", async () => {
    const fake = fakeFetch([
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, body: reviewTaskDetailDto() },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
      { path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`, body: documentDto() },
      {
        path: `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`,
        body: documentDetailDto({ document_id: EXAMPLE_DOCUMENT_ID }),
      },
      { path: "/v1/rulebook/rules/example_rule/versions", body: [ruleVersionDto()] },
    ]);
    const page = await getWorkbench(SESSION, EXAMPLE_TASK_ID, { fetchImpl: fake.fetchImpl });
    if (!page.ok || page.value === null) throw new Error("expected the workbench");
    expect(page.value.source.documents[0]?.file).toMatchObject({ kind: "stored", type: "PDF" });
    expect(page.value.editorOntology).not.toBeNull();
    expect(page.value.comparisons.previous).toBeNull();
    expect(fake.requests.map((request) => request.pathname).sort()).toEqual(
      [
        `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`,
        "/v1/ontology",
        `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`,
        `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`,
        "/v1/rulebook/rules/example_rule/versions",
      ].sort(),
    );
  });

  it("reads the draft form's relations, rules and versions for the claimant of a candidate task", async () => {
    const claimed = candidateTaskDetailDto({
      task: reviewTaskDto({
        task_id: EXAMPLE_CANDIDATE_TASK_ID,
        rule_version_id: null,
        kind: "candidate",
        status: "claimed",
        claimed_by: SESSION.userId,
      }),
    });
    const fake = fakeFetch([
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`, body: claimed },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
      { path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`, body: documentDto() },
      { path: `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`, status: 404, problem: {} },
      {
        path: "/v1/rulebook/review/relations",
        body: [relationCandidateDto({ relation: "supersedes" })],
      },
      { path: "/v1/rulebook/rules", body: [ruleDto(), ruleDto({ rule_key: "example_gone" })] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        body: [ruleVersionDto({ status: "published" })],
      },
      { path: "/v1/rulebook/rules/example_gone/versions", status: 404, problem: {} },
    ]);
    const page = await getWorkbench(SESSION, EXAMPLE_CANDIDATE_TASK_ID, {
      fetchImpl: fake.fetchImpl,
    });
    if (!page.ok || page.value === null) throw new Error("expected the workbench");
    const form = page.value.rule.draftForm;
    expect(form?.ruleKeys).toEqual(["example_gone", "example_rule"]);
    expect(form?.relations[0]).toMatchObject({
      needsTarget: true,
      targetOptions: [{ label: "example_rule v1 (Published)" }],
    });
    expect(page.value.source.documents[0]?.file).toEqual({ kind: "none" });
    // Every candidate names its target's rule, so only that rule's versions are read.
    const read = fake.requests.map((request) => request.pathname);
    expect(read).toContain("/v1/rulebook/rules/example_rule/versions");
    expect(read).not.toContain("/v1/rulebook/rules/example_gone/versions");
  });

  it("reads every rule's versions when a candidate names no target rule", async () => {
    const claimed = candidateTaskDetailDto({
      task: reviewTaskDto({
        task_id: EXAMPLE_CANDIDATE_TASK_ID,
        rule_version_id: null,
        kind: "candidate",
        status: "claimed",
        claimed_by: SESSION.userId,
      }),
    });
    const fake = fakeFetch([
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`, body: claimed },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
      { path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`, body: documentDto() },
      { path: `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`, status: 404, problem: {} },
      {
        path: "/v1/rulebook/review/relations",
        body: [
          relationCandidateDto({ relation: "supersedes" }),
          relationCandidateDto({
            candidate_id: "00000000-0000-4000-8000-0000000000cc",
            relation: "refers_to",
            target_rule_key: null,
          }),
        ],
      },
      { path: "/v1/rulebook/rules", body: [ruleDto(), ruleDto({ rule_key: "example_other" })] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        body: [ruleVersionDto({ status: "published" })],
      },
      {
        path: "/v1/rulebook/rules/example_other/versions",
        body: [
          ruleVersionDto({
            rule_version_id: "00000000-0000-4000-8000-0000000000f9",
            rule_key: "example_other",
          }),
        ],
      },
    ]);
    const page = await getWorkbench(SESSION, EXAMPLE_CANDIDATE_TASK_ID, {
      fetchImpl: fake.fetchImpl,
    });
    if (!page.ok || page.value === null) throw new Error("expected the workbench");
    const [named, open] = page.value.rule.draftForm?.relations ?? [];
    expect(named?.targetOptions.map((option) => option.label)).toEqual([
      "example_rule v1 (Published)",
    ]);
    expect(open?.targetOptions.map((option) => option.label)).toEqual([
      "example_other v1 (Draft)",
      "example_rule v1 (Published)",
    ]);
  });

  it("reads the relations a draft may take on again for the action, none for a seed task", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`,
        body: candidateTaskDetailDto(),
      },
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, body: reviewTaskDetailDto() },
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        body: [ruleVersionDto({ status: "published" })],
      },
    ]);
    expect(
      await relationsOffered(EXAMPLE_CANDIDATE_TASK_ID, { fetchImpl: fake.fetchImpl }),
    ).toMatchObject({
      ok: true,
      value: [{ needsTarget: true, targetOptions: [{ label: "example_rule v1 (Published)" }] }],
    });
    expect(await relationsOffered(EXAMPLE_TASK_ID, { fetchImpl: fake.fetchImpl })).toEqual({
      ok: true,
      value: [],
    });
    const failing = fakeFetch([
      {
        path: `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`,
        body: candidateTaskDetailDto(),
      },
      { path: "/v1/rulebook/review/relations", status: 503, problem: { title: "Example outage" } },
    ]);
    expect(
      await relationsOffered(EXAMPLE_CANDIDATE_TASK_ID, { fetchImpl: failing.fetchImpl }),
    ).toMatchObject({ ok: false, error: { message: "Example outage" } });
  });

  it("says the relations could not be read when every rule's versions fail", async () => {
    const claimed = candidateTaskDetailDto({
      task: reviewTaskDto({
        task_id: EXAMPLE_CANDIDATE_TASK_ID,
        rule_version_id: null,
        kind: "candidate",
        status: "claimed",
        claimed_by: SESSION.userId,
      }),
    });
    const fake = fakeFetch([
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_CANDIDATE_TASK_ID}`, body: claimed },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
      { path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`, body: documentDto() },
      { path: `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`, status: 404, problem: {} },
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
      { path: "/v1/rulebook/rules", body: [ruleDto()] },
      {
        path: "/v1/rulebook/rules/example_rule/versions",
        status: 500,
        problem: { title: "Example failure" },
      },
    ]);
    const page = await getWorkbench(SESSION, EXAMPLE_CANDIDATE_TASK_ID, {
      fetchImpl: fake.fetchImpl,
    });
    if (!page.ok || page.value === null) throw new Error("expected the workbench");
    expect(page.value.rule.draftForm?.relationsError).toMatchObject({ message: "Example failure" });
  });
});

describe("taskNow", () => {
  it("reads a task again, null when it is gone", async () => {
    expect(
      await taskNow(EXAMPLE_TASK_ID, {
        fetchImpl: fakeFetch([
          { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, body: reviewTaskDetailDto() },
        ]).fetchImpl,
      }),
    ).toMatchObject({ ok: true, value: { task: { taskId: EXAMPLE_TASK_ID } } });
    expect(
      await taskNow(EXAMPLE_TASK_ID, {
        fetchImpl: fakeFetch([
          { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, status: 404, problem: {} },
        ]).fetchImpl,
      }),
    ).toEqual({ ok: true, value: null });
    expect(
      await taskNow(EXAMPLE_TASK_ID, {
        fetchImpl: fakeFetch([
          { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, status: 500, problem: {} },
        ]).fetchImpl,
      }),
    ).toMatchObject({ ok: false });
  });
});
