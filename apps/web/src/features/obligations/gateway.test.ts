// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { IDEMPOTENCY_KEY_HEADER, REPLAYED_HEADER } from "@/server/api/idempotency";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO } from "@/test/business-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import {
  CLAUSE_ID,
  DOCUMENT_ID,
  OBLIGATION_ID,
  REGISTRATION_ID,
  RULE_VERSION_ID,
  TENANT_ID,
  USER_ID,
  commentDto,
  decisionDto,
  decisionPageDto,
  listedObligationDto,
  obligationDetailDto,
  obligationDto,
  obligationPageDto,
} from "@/test/obligation-fixture";
import { obligationsGateway } from "./gateway";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};
const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";
const ONE = `/v1/obligation/obligations/${OBLIGATION_ID}`;

afterEach(() => {
  resetEnvCache();
});

function gateway(fake: ReturnType<typeof fakeFetch>) {
  return obligationsGateway({ session, fetchImpl: fake.fetchImpl });
}

describe("ObligationsGateway reads", () => {
  it("lists one node's obligations with the filter, the tenant header and no cache", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/businesses/${REGISTRATION_ID}/obligations`,
        body: obligationPageDto([listedObligationDto()], "next-1"),
      },
    ]);
    const page = await gateway(fake).list(REGISTRATION_ID, {
      statuses: ["open", "in_progress"],
      dueFrom: "2000-01-01",
      dueTo: "2000-01-31",
      limit: 26,
      cursor: "after-1",
    });
    expect(page.ok && page.value.items[0]?.title).toBe("Example return 1");
    expect(page.ok && page.value.nextCursor).toBe("next-1");
    const [request] = fake.requests;
    const url = new URL(request?.url ?? "");
    expect(url.origin).toBe("http://localhost:8005");
    expect(url.searchParams.getAll("status")).toEqual(["open", "in_progress"]);
    expect(url.searchParams.get("due_from")).toBe("2000-01-01");
    expect(url.searchParams.get("due_to")).toBe("2000-01-31");
    expect(url.searchParams.get("limit")).toBe("26");
    expect(url.searchParams.get("cursor")).toBe("after-1");
    expect(request?.headers[TENANT_HEADER]).toBe(TENANT_ID);
    expect(request?.cache).toBe("no-store");
  });

  it("sends no filter it was not given", async () => {
    const fake = fakeFetch([
      { path: `/v1/businesses/${REGISTRATION_ID}/obligations`, body: obligationPageDto([]) },
    ]);
    await gateway(fake).list(REGISTRATION_ID, {
      statuses: [],
      dueFrom: null,
      dueTo: null,
      limit: 1,
    });
    expect(new URL(fake.requests[0]?.url ?? "").search).toBe("?limit=1");
  });

  it("reads the business, one obligation, the latest decision and a cited clause", async () => {
    const fake = fakeFetch([
      { path: `/v1/businesses/${REGISTRATION_ID}`, body: BUSINESS_DTO },
      { path: ONE, body: obligationDetailDto() },
      {
        path: `/v1/applicability-engine/businesses/${REGISTRATION_ID}/decisions`,
        body: decisionPageDto([decisionDto()]),
      },
      {
        path: `/v1/rulebook/clauses/${CLAUSE_ID}`,
        body: {
          clause_id: CLAUSE_ID,
          document_id: DOCUMENT_ID,
          clause_ref: "en.p2",
          ordinal: 2,
          page: 1,
          text: "Example whole clause text",
          regulator: "Example regulator",
          doc_type: "circular",
          external_ref: "Example 1/2000",
          title: "Example document title",
          url: "https://example.com/example.pdf",
          language: "en",
          published_at: null,
        },
      },
    ]);
    const g = gateway(fake);
    expect((await g.business(REGISTRATION_ID)).ok).toBe(true);
    const detail = await g.detail(OBLIGATION_ID);
    expect(detail.ok && detail.value.history).toHaveLength(1);
    const decision = await g.latestDecision(REGISTRATION_ID, RULE_VERSION_ID);
    expect(decision.ok && decision.value?.result).toBe("applies");
    const clause = await g.clause(CLAUSE_ID);
    expect(clause.ok && clause.value.text).toBe("Example whole clause text");

    const [, , engine, rulebook] = fake.requests;
    const query = new URL(engine?.url ?? "").searchParams;
    expect(query.get("rule_version_id")).toBe(RULE_VERSION_ID);
    expect(query.get("limit")).toBe("1");
    expect(engine?.headers[TENANT_HEADER]).toBe(TENANT_ID);
    expect(new URL(engine?.url ?? "").origin).toBe("http://localhost:8004");
    // A clause is the same for every tenant: no tenant header, kept under its tag.
    expect(rulebook?.headers[TENANT_HEADER]).toBeUndefined();
    expect(rulebook?.next?.tags).toEqual([`rulebook:clause:${CLAUSE_ID}`]);
  });

  it("answers no decision when the engine holds none for the node and version", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/applicability-engine/businesses/${REGISTRATION_ID}/decisions`,
        body: decisionPageDto([]),
      },
    ]);
    const decision = await gateway(fake).latestDecision(REGISTRATION_ID, RULE_VERSION_ID);
    expect(decision).toMatchObject({ ok: true, value: null });
  });

  it("lists the tenant's active users by name only", async () => {
    const user = (id: string, status: "active" | "disabled") => ({
      id,
      tenant_id: TENANT_ID,
      email: "example@example.com",
      phone: "+910000000001",
      display_name: `Example ${id}`,
      roles: ["staff"],
      status,
      session_version: 1,
      created_at: "2000-01-01T00:00:00Z",
      updated_at: "2000-01-01T00:00:00Z",
    });
    const fake = fakeFetch([
      {
        path: "/v1/identity/users",
        body: { items: [user("u1", "active"), user("u2", "disabled")] },
      },
    ]);
    const members = await gateway(fake).members();
    expect(members.ok && members.value).toEqual([
      { id: "u1", name: "Example u1", roles: ["staff"] },
    ]);
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT_ID);
  });
});

describe("ObligationsGateway writes", () => {
  it("changes a status with the form's key and says whether the answer was a replay", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${ONE}/status`,
        body: obligationDto({ status: "waived" }),
        headers: { [REPLAYED_HEADER]: "true" },
      },
    ]);
    const changed = await gateway(fake).changeStatus(
      OBLIGATION_ID,
      { action: "waive", reason: " Example waiver reason " },
      { [IDEMPOTENCY_KEY_HEADER]: FORM_UUID },
    );
    expect(changed.ok && changed.value).toMatchObject({
      replayed: true,
      value: { status: "waived" },
    });
    const [request] = fake.requests;
    expect(request?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);
    expect(request?.body).toEqual({ action: "waive", reason: "Example waiver reason" });
  });

  it("gives an obligation to a user or to nobody, and adds a comment", async () => {
    const fake = fakeFetch([
      {
        method: "PUT",
        path: `${ONE}/assignee`,
        body: obligationDto({ assignee_id: USER_ID }),
      },
      { method: "POST", path: `${ONE}/comments`, status: 201, body: commentDto() },
    ]);
    const g = gateway(fake);
    const given = await g.assign(OBLIGATION_ID, USER_ID, { [IDEMPOTENCY_KEY_HEADER]: FORM_UUID });
    expect(given.ok && given.value).toMatchObject({
      replayed: false,
      value: { assigneeId: USER_ID },
    });
    await g.assign(OBLIGATION_ID, null, {});
    const comment = await g.comment(OBLIGATION_ID, "Example comment", {
      [IDEMPOTENCY_KEY_HEADER]: FORM_UUID,
    });
    expect(comment.ok && comment.value.value.body).toBe("Example comment");
    expect(fake.requests.map((request) => request.body)).toEqual([
      { assignee_id: USER_ID },
      { assignee_id: null },
      { body: "Example comment" },
    ]);
    // Without a key the service answers its 428; the gateway never invents one.
    expect(fake.requests[1]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBeUndefined();
  });

  it("passes a refusal on as an ApiError and reports an answer without a body", async () => {
    const fake = fakeFetch([
      { method: "POST", path: `${ONE}/status`, status: 409, problem: { title: "Example closed" } },
      { method: "PUT", path: `${ONE}/assignee`, status: 200 },
    ]);
    const refused = await gateway(fake).changeStatus(
      OBLIGATION_ID,
      { action: "complete", reason: "" },
      {},
    );
    expect(refused.ok ? null : refused.error.kind).toBe("conflict");
    const empty = await gateway(fake).assign(OBLIGATION_ID, null, {});
    expect(empty.ok ? null : empty.error.problem?.type).toBe(
      "urn:compliancewatch:problem:web-empty-body",
    );
  });
});
