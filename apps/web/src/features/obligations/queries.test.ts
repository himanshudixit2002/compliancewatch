// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO } from "@/test/business-fixture";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import {
  CLAUSE_ID,
  ENTITY_ID,
  NOW,
  OBLIGATION_ID,
  REGISTRATION_ID,
  TENANT_ID,
  USER_ID,
  decisionDto,
  decisionPageDto,
  dueAt,
  listedObligationDto,
  obligationDetailDto,
  obligationPageDto,
} from "@/test/obligation-fixture";
import { encodeListKey, readListFilter } from "./model/list";
import { findFirstObligation, getCalendar, getObligation, getObligationList } from "./queries";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  resetEnvCache();
});

function id(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

function row(n: number, day: string | null, node = REGISTRATION_ID) {
  return listedObligationDto({
    obligation_id: id(n),
    business_id: node,
    due_at: day === null ? null : dueAt(day),
    title: `Example return ${n}`,
  });
}

const LIST = /^\/v1\/businesses\/([^/]+)\/obligations$/;

/** The service's list for each node: its rows from due_from on, a page of `limit` at a time. */
function nodeLists(
  rows: Record<string, ReturnType<typeof row>[]>,
): (request: RecordedRequest) => Response {
  return (request) => {
    if (request.pathname === `/v1/businesses/${ENTITY_ID}`) return jsonResponse(200, BUSINESS_DTO);
    const match = LIST.exec(request.pathname);
    if (match === null) return problemResponse(404);
    const query = new URL(request.url).searchParams;
    const from = query.get("due_from");
    const limit = Number(query.get("limit"));
    const start = Number(query.get("cursor") ?? "0");
    // The service's order: due date first, the undated last, then id.
    const all = (rows[match[1] as string] ?? [])
      .filter(
        (item) => from === null || (item.due_at !== null && item.due_at >= `${from}T00:00:00`),
      )
      .sort(
        (a, b) =>
          (a.due_at ?? "~").localeCompare(b.due_at ?? "~") ||
          a.obligation_id.localeCompare(b.obligation_id),
      );
    const items = all.slice(start, start + limit);
    const next = start + limit < all.length ? String(start + limit) : null;
    return jsonResponse(200, obligationPageDto(items, next));
  };
}

describe("getObligationList", () => {
  it("merges the entity's and the registration's obligations by due date", async () => {
    const fake = fakeFetch(
      nodeLists({
        [ENTITY_ID]: [row(1, "2000-01-15", ENTITY_ID)],
        [REGISTRATION_ID]: [row(2, "2000-01-10"), row(3, "2000-01-20"), row(4, null)],
      }),
    );
    const list = await getObligationList(session, ENTITY_ID, readListFilter({}), {
      fetchImpl: fake.fetchImpl,
      now: NOW,
    });
    expect(list.ok).toBe(true);
    if (!list.ok) return;
    expect(list.value.rows.map((item) => item.title)).toEqual([
      "Example return 2",
      "Example return 1",
      "Example return 3",
      "Example return 4",
    ]);
    expect(list.value.nodes).toBe(2);
    expect(list.value.rows[1]?.node).toBe("Example business (PAN ABCDE1234F)");
    expect(list.value.nextHref).toBeNull();
    expect(list.value.firstHref).toBeNull();
    expect(list.value.rows[0]?.href).toBe(`/b/${ENTITY_ID}/obligations/${id(2)}`);
  });

  it("reads the latest decision once per node and rule version, and marks a failed read", async () => {
    const decisions: string[] = [];
    const lists = nodeLists({
      [ENTITY_ID]: [row(1, "2000-01-15", ENTITY_ID)],
      [REGISTRATION_ID]: [row(2, "2000-01-10"), row(3, "2000-01-20")],
    });
    const fake = fakeFetch((request) => {
      const decided = /^\/v1\/applicability-engine\/businesses\/([^/]+)\/decisions$/.exec(
        request.pathname,
      );
      if (decided === null) return lists(request);
      decisions.push(request.url);
      if (decided[1] === ENTITY_ID) return problemResponse(503);
      return jsonResponse(
        200,
        decisionPageDto([decisionDto({ result: "unsure", needs_review: true })]),
      );
    });
    const list = await getObligationList(session, ENTITY_ID, readListFilter({}), {
      fetchImpl: fake.fetchImpl,
      now: NOW,
    });
    if (!list.ok) throw new Error(list.error.message);
    expect(list.value.rows.map((item) => [item.title, item.applicability])).toEqual([
      ["Example return 2", { state: "decided", result: "unsure", needsReview: true }],
      ["Example return 1", { state: "unknown" }],
      ["Example return 3", { state: "decided", result: "unsure", needsReview: true }],
    ]);
    // The registration's two periods share one rule version: one read.
    expect(decisions).toHaveLength(2);
    expect(decisions.every((url) => url.includes("limit=1"))).toBe(true);
  });

  it("says a node has no decision of the version", async () => {
    const lists = nodeLists({ [REGISTRATION_ID]: [row(2, "2000-01-10")] });
    const fake = fakeFetch((request) =>
      request.pathname.endsWith("/decisions")
        ? jsonResponse(200, decisionPageDto([]))
        : lists(request),
    );
    const list = await getObligationList(session, ENTITY_ID, readListFilter({}), {
      fetchImpl: fake.fetchImpl,
      now: NOW,
    });
    expect(list.ok && list.value.rows[0]?.applicability).toEqual({ state: "none" });
  });

  it("pages after the last row's key, asking each node from its due day", async () => {
    const many = Array.from({ length: 30 }, (_, index) =>
      row(index + 1, `2000-01-${String((index % 28) + 1).padStart(2, "0")}`),
    );
    const fake = fakeFetch(nodeLists({ [ENTITY_ID]: [], [REGISTRATION_ID]: many }));
    const first = await getObligationList(session, ENTITY_ID, readListFilter({ status: "todo" }), {
      fetchImpl: fake.fetchImpl,
      now: NOW,
    });
    if (!first.ok) throw new Error("first page failed");
    expect(first.value.rows).toHaveLength(25);
    expect(first.value.nextHref).not.toBeNull();
    const next = new URL(first.value.nextHref ?? "", "http://localhost");
    expect(next.searchParams.get("status")).toBe("todo");
    const listRequests = fake.requests.filter((request) => LIST.test(request.pathname));
    expect(new URL(listRequests[0]?.url ?? "").searchParams.getAll("status")).toEqual([
      "open",
      "in_progress",
    ]);

    fake.requests.length = 0;
    const second = await getObligationList(
      session,
      ENTITY_ID,
      readListFilter(Object.fromEntries(next.searchParams)),
      { fetchImpl: fake.fetchImpl, now: NOW },
    );
    if (!second.ok) throw new Error("second page failed");
    const seen = new Set(first.value.rows.map((item) => item.id));
    expect(second.value.rows.length).toBe(5);
    expect(second.value.rows.every((item) => !seen.has(item.id))).toBe(true);
    expect(second.value.nextHref).toBeNull();
    expect(second.value.firstHref).toBe(`/b/${ENTITY_ID}/obligations?status=todo`);
    const registration = fake.requests.find(
      (request) => request.pathname === `/v1/businesses/${REGISTRATION_ID}/obligations`,
    );
    const lastDay = first.value.rows.at(-1)?.due;
    expect(lastDay).toBeDefined();
    expect(new URL(registration?.url ?? "").searchParams.get("due_from")).toMatch(/^2000-01-\d\d$/);
  });

  it("asks nothing for a window the service would refuse", async () => {
    const fake = fakeFetch(nodeLists({}));
    const list = await getObligationList(
      session,
      ENTITY_ID,
      readListFilter({ from: "2000-01-01", to: "2001-06-30" }),
      { fetchImpl: fake.fetchImpl },
    );
    expect(list.ok && list.value.asked).toBe(false);
    expect(fake.requests.some((request) => LIST.test(request.pathname))).toBe(false);
  });

  it("passes on a missing business and a failed node", async () => {
    const missing = fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} }]);
    const notFound = await getObligationList(session, ENTITY_ID, readListFilter({}), {
      fetchImpl: missing.fetchImpl,
    });
    expect(notFound.ok ? null : notFound.error.kind).toBe("not_found");
    const failing = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: LIST, status: 503, problem: { title: "Example unavailable" } },
    ]);
    const down = await getObligationList(session, ENTITY_ID, readListFilter({}), {
      fetchImpl: failing.fetchImpl,
    });
    expect(down.ok ? null : down.error.kind).toBe("unavailable");
  });

  it("says so rather than guess when a node has too many rows before the key", async () => {
    const sameDay = Array.from({ length: 900 }, (_, index) => row(index + 1, "2000-01-05"));
    const fake = fakeFetch(nodeLists({ [ENTITY_ID]: [], [REGISTRATION_ID]: sameDay }));
    const after = encodeListKey({ dueAt: dueAt("2000-01-05"), id: id(899) });
    const list = await getObligationList(session, ENTITY_ID, readListFilter({ after }), {
      fetchImpl: fake.fetchImpl,
    });
    expect(list.ok ? null : list.error.problem?.type).toBe(
      "urn:compliancewatch:problem:web-obligation-list-too-long",
    );
  });
});

describe("getCalendar", () => {
  it("reads every node's month and puts the obligations on their days", async () => {
    const fake = fakeFetch(
      nodeLists({
        [ENTITY_ID]: [row(1, "2000-02-03", ENTITY_ID)],
        [REGISTRATION_ID]: [row(2, "2000-02-20"), row(3, "2000-02-20")],
      }),
    );
    const page = await getCalendar(
      session,
      ENTITY_ID,
      { year: 2000, month: 2 },
      {
        fetchImpl: fake.fetchImpl,
        now: NOW,
      },
    );
    if (!page.ok) throw new Error("calendar failed");
    expect(page.value.calendar.total).toBe(3);
    expect(Object.keys(page.value.calendar.days)).toEqual(["2000-02-03", "2000-02-20"]);
    expect(page.value.calendar.cut).toBe(false);
    const query = new URL(fake.requests.find((request) => LIST.test(request.pathname))?.url ?? "")
      .searchParams;
    expect(query.get("due_from")).toBe("2000-02-01");
    expect(query.get("due_to")).toBe("2000-02-29");
    expect(query.get("limit")).toBe("200");
  });

  it("passes on a missing business", async () => {
    const fake = fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} }]);
    const page = await getCalendar(
      session,
      ENTITY_ID,
      { year: 2000, month: 2 },
      {
        fetchImpl: fake.fetchImpl,
      },
    );
    expect(page.ok).toBe(false);
  });
});

describe("getObligation", () => {
  const ONE = `/v1/obligation/obligations/${OBLIGATION_ID}`;
  const DECISIONS = `/v1/applicability-engine/businesses/${REGISTRATION_ID}/decisions`;
  const CLAUSE = `/v1/rulebook/clauses/${CLAUSE_ID}`;
  const USERS = "/v1/identity/users";

  it("reads the obligation with why it applies, its clauses and, for an admin, the users", async () => {
    const fake = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: ONE, body: obligationDetailDto() },
      { path: DECISIONS, body: decisionPageDto([decisionDto()]) },
      { path: CLAUSE, status: 503, problem: { title: "Example unavailable" } },
      {
        path: USERS,
        body: {
          items: [
            {
              id: USER_ID,
              tenant_id: TENANT_ID,
              email: "owner@example.com",
              phone: "+910000000001",
              display_name: "Example owner",
              roles: ["owner"],
              status: "active",
              session_version: 1,
              created_at: "2000-01-01T00:00:00Z",
              updated_at: "2000-01-01T00:00:00Z",
            },
          ],
        },
      },
    ]);
    const page = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: true },
      {
        fetchImpl: fake.fetchImpl,
        now: NOW,
      },
    );
    if (!page.ok) throw new Error("detail failed");
    expect(page.value.obligation.node).toBe("29ABCDE1234F1Z5 (Example registration)");
    expect(page.value.obligation.why.state).toBe("decided");
    // A clause that could not be read leaves the verified quote, without the clause's text.
    expect(page.value.obligation.citations[0]).toMatchObject({
      quote: "Example quoted clause text.",
      clauseText: null,
    });
    expect(page.value.assignee).toEqual({
      kind: "members",
      members: [{ id: USER_ID, name: "Example owner", roles: ["owner"] }],
    });
    expect(page.value.listHref).toBe(`/b/${ENTITY_ID}/obligations`);
  });

  it("offers an id field when the role cannot list users or identity cannot answer", async () => {
    const routes = [
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: ONE, body: obligationDetailDto({ citations: [] }) },
      { path: DECISIONS, status: 503, problem: { title: "Example engine down" } },
      { path: USERS, status: 401, problem: { title: "Example token needed" } },
    ];
    const staff = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: false },
      {
        fetchImpl: fakeFetch(routes).fetchImpl,
      },
    );
    if (!staff.ok) throw new Error("detail failed");
    expect(staff.value.assignee).toEqual({ kind: "id", reason: "role" });
    expect(staff.value.obligation.why).toMatchObject({ state: "error" });
    const admin = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: true },
      {
        fetchImpl: fakeFetch(routes).fetchImpl,
      },
    );
    expect(admin.ok && admin.value.assignee).toEqual({ kind: "id", reason: "unavailable" });
  });

  it("finds no obligation of another business, and passes a missing one on", async () => {
    const other = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: ONE, body: obligationDetailDto({ business_id: id(77) }) },
    ]);
    const elsewhere = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: false },
      {
        fetchImpl: other.fetchImpl,
      },
    );
    expect(elsewhere.ok ? null : elsewhere.error.kind).toBe("not_found");
    const missing = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: ONE, status: 404, problem: {} },
    ]);
    const gone = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: false },
      {
        fetchImpl: missing.fetchImpl,
      },
    );
    expect(gone.ok ? null : gone.error.kind).toBe("not_found");
    const noBusiness = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} },
    ]);
    const none = await getObligation(
      session,
      ENTITY_ID,
      OBLIGATION_ID,
      { canListMembers: false },
      {
        fetchImpl: noBusiness.fetchImpl,
      },
    );
    expect(none.ok).toBe(false);
  });
});

describe("findFirstObligation", () => {
  it("names the business's first obligation by due date across its nodes", async () => {
    const fake = fakeFetch(
      nodeLists({
        [ENTITY_ID]: [row(1, "2000-01-25", ENTITY_ID)],
        [REGISTRATION_ID]: [row(2, "2000-01-20")],
      }),
    );
    const found = await findFirstObligation(session, ENTITY_ID, {
      fetchImpl: fake.fetchImpl,
      now: NOW,
    });
    expect(found).toEqual({
      status: "found",
      title: "Example return 2",
      due: "20 Jan 2000",
      dueNote: "Due in 10 days",
      href: `/b/${ENTITY_ID}/obligations/${id(2)}`,
    });
    for (const request of fake.requests.filter((item) => LIST.test(item.pathname))) {
      expect(new URL(request.url).searchParams.get("limit")).toBe("1");
    }
  });

  it("says none yet, or what failed", async () => {
    const empty = fakeFetch(nodeLists({}));
    expect(await findFirstObligation(session, ENTITY_ID, { fetchImpl: empty.fetchImpl })).toEqual({
      status: "none",
    });
    const down = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: LIST, status: 503, problem: { title: "Example unavailable" } },
    ]);
    expect(
      await findFirstObligation(session, ENTITY_ID, { fetchImpl: down.fetchImpl }),
    ).toMatchObject({
      status: "error",
      message: "Example unavailable",
    });
    const missing = fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} }]);
    expect(
      await findFirstObligation(session, ENTITY_ID, { fetchImpl: missing.fetchImpl }),
    ).toMatchObject({ status: "error" });
  });
});
