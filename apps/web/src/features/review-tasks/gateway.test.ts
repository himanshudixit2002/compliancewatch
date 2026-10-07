// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER, WRITE_TOKEN_HEADER } from "@/server/api/client";
import { REVIEW_TOKEN_HEADER } from "@/server/api/rulebook-write";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { documentDetailDto } from "@/test/pipeline-fixture";
import { EXAMPLE_DOCUMENT_ID, documentDto, relationCandidateDto } from "@/test/rulebook-fixture";
import { ruleDto, ruleVersionDto } from "@/test/rule-version-fixture";
import {
  EXAMPLE_TASK_ID,
  queuedTaskDto,
  reviewStatsDto,
  reviewTaskDetailDto,
  taskPageDto,
} from "@/test/review-task-fixture";
import { RELATIONS_LIMIT, reviewTasksGateway } from "./gateway";

afterEach(() => {
  resetEnvCache();
});

describe("ReviewTasksGateway", () => {
  it("reads a page of the queue with its filters and cursor, fresh, without a tenant or a token", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/tasks", body: taskPageDto([queuedTaskDto()], "next") },
    ]);
    const page = await reviewTasksGateway({ fetchImpl: fake.fetchImpl }).tasks({
      status: "claimed",
      regulator: "example_regulator",
      kind: "seed",
      cursor: "example-cursor",
      limit: 25,
    });
    expect(page).toMatchObject({ ok: true, value: { nextCursor: "next" } });
    const request = fake.requests[0];
    expect(request?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/tasks?limit=25&status=claimed&regulator=example_regulator&kind=seed&cursor=example-cursor",
    );
    expect(request?.cache).toBe("no-store");
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[REVIEW_TOKEN_HEADER]).toBeUndefined();
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
  });

  it("leaves out each filter the queue does not set", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/review/tasks", body: taskPageDto([]) }]);
    await reviewTasksGateway({ fetchImpl: fake.fetchImpl }).tasks({
      status: null,
      regulator: null,
      kind: null,
      cursor: null,
      limit: 25,
    });
    expect(fake.requests[0]?.url).toBe("http://localhost:8003/v1/rulebook/review/tasks?limit=25");
  });

  it("reads a task, the stats and the open relations of a document fresh", async () => {
    const fake = fakeFetch([
      { path: `/v1/rulebook/review/tasks/${EXAMPLE_TASK_ID}`, body: reviewTaskDetailDto() },
      { path: "/v1/rulebook/review/stats", body: reviewStatsDto() },
      { path: "/v1/rulebook/review/relations", body: [relationCandidateDto()] },
    ]);
    const gateway = reviewTasksGateway({ fetchImpl: fake.fetchImpl });
    expect((await gateway.task(EXAMPLE_TASK_ID)).ok).toBe(true);
    expect(await gateway.stats()).toMatchObject({ ok: true, value: { byStatus: { open: 3 } } });
    expect((await gateway.openRelations(EXAMPLE_DOCUMENT_ID)).ok).toBe(true);
    expect(fake.requests.map((request) => request.cache)).toEqual([
      "no-store",
      "no-store",
      "no-store",
    ]);
    expect(fake.requests[2]?.url).toBe(
      `http://localhost:8003/v1/rulebook/review/relations?status=open&document_id=${EXAMPLE_DOCUMENT_ID}&limit=${RELATIONS_LIMIT}`,
    );
  });

  it("caches a document and the rules under their tags, and reads a rule's versions fresh", async () => {
    const fake = fakeFetch([
      { path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`, body: documentDto() },
      { path: "/v1/rulebook/rules", body: [ruleDto()] },
      { path: "/v1/rulebook/rules/example_rule/versions", body: [ruleVersionDto()] },
    ]);
    const gateway = reviewTasksGateway({ fetchImpl: fake.fetchImpl });
    expect(await gateway.document(EXAMPLE_DOCUMENT_ID)).toMatchObject({
      ok: true,
      value: { documentId: EXAMPLE_DOCUMENT_ID },
    });
    expect(await gateway.rules()).toMatchObject({ ok: true, value: [{ ruleKey: "example_rule" }] });
    expect(await gateway.versionsOf("example_rule")).toMatchObject({
      ok: true,
      value: [{ ruleKey: "example_rule" }],
    });
    expect(fake.requests[0]?.next?.tags).toEqual([`rulebook:document:${EXAMPLE_DOCUMENT_ID}`]);
    expect(fake.requests[1]?.next?.tags).toEqual(["rulebook:rules"]);
    expect(fake.requests[2]?.cache).toBe("no-store");
  });

  it("reads the pipeline's record of a stored file, without a tenant, and passes its 404 on", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`,
        body: documentDetailDto({ document_id: EXAMPLE_DOCUMENT_ID }),
      },
      { path: /\/v1\/pipeline\/documents\/.+/, status: 404, problem: { title: "Example missing" } },
    ]);
    const gateway = reviewTasksGateway({ fetchImpl: fake.fetchImpl });
    expect(await gateway.storedDocument(EXAMPLE_DOCUMENT_ID)).toMatchObject({
      ok: true,
      value: { documentId: EXAMPLE_DOCUMENT_ID, contentType: "application/pdf" },
    });
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8010/v1/pipeline/documents/${EXAMPLE_DOCUMENT_ID}`,
    );
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    const missing = await gateway.storedDocument("00000000-0000-0000-0000-000000000000");
    expect(missing).toMatchObject({ ok: false, error: { kind: "not_found" } });
  });
});
