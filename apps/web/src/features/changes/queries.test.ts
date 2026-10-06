// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO } from "@/test/business-fixture";
import {
  CHANGED_VERSION_ID,
  changeImpactDto,
  ruleChangeDto,
  ruleChangePageDto,
} from "@/test/change-fixture";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { CLAUSE_ID, ENTITY_ID, TENANT_ID, USER_ID } from "@/test/obligation-fixture";
import { getChanges } from "./queries";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};
const IMPACT = `/v1/changes/${CHANGED_VERSION_ID}/impact`;
const OTHER_ENTITY = "00000000-0000-4000-8000-0000000000e9";

afterEach(() => {
  resetEnvCache();
});

describe("getChanges", () => {
  it("reads the feed and, for each version once, whether it applies to this business", async () => {
    const fake = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      {
        path: "/v1/changes",
        body: ruleChangePageDto(
          [
            ruleChangeDto({ change_id: "00000000-0000-4000-8000-00000000c0c2", kind: "withdrawn" }),
            ruleChangeDto(),
          ],
          "next-1",
        ),
      },
      { path: IMPACT, body: changeImpactDto([{ result: "applies" }]) },
      { path: `/v1/rulebook/clauses/${CLAUSE_ID}`, status: 503, problem: {} },
    ]);
    const changes = await getChanges(session, ENTITY_ID, null, { fetchImpl: fake.fetchImpl });
    if (!changes.ok) throw new Error("changes failed");
    expect(changes.value.cards.map((card) => card.kindLabel)).toEqual(["Withdrawn", "Published"]);
    expect(changes.value.cards.every((card) => card.applicability.value === "applies")).toBe(true);
    expect(changes.value.cards[0]?.applicability.details[0]).toBe(
      "29ABCDE1234F1Z5 (Example registration): applies, decided on 5 Jan 2000",
    );
    expect(fake.requests.filter((request) => request.pathname === IMPACT)).toHaveLength(1);
    expect(changes.value.nextHref).toBe(`/b/${ENTITY_ID}/changes?cursor=next-1`);
    expect(changes.value.firstHref).toBeNull();
  });

  it("walks the impact's pages of clients to this business, or says it is not decided", async () => {
    let page = 0;
    const fake = fakeFetch((request) => {
      if (request.pathname === `/v1/businesses/${ENTITY_ID}`)
        return jsonResponse(200, BUSINESS_DTO);
      if (request.pathname === "/v1/changes") {
        return jsonResponse(200, ruleChangePageDto([ruleChangeDto({ citations: [] })]));
      }
      if (request.pathname === IMPACT) {
        page += 1;
        return page === 1
          ? jsonResponse(
              200,
              changeImpactDto([{ entityId: OTHER_ENTITY, result: "applies" }], {
                next_cursor: "p2",
              }),
            )
          : jsonResponse(200, changeImpactDto([{ result: "not_applicable" }]));
      }
      return problemResponse(404);
    });
    const changes = await getChanges(session, ENTITY_ID, "after-1", { fetchImpl: fake.fetchImpl });
    if (!changes.ok) throw new Error("changes failed");
    expect(changes.value.cards[0]?.applicability.value).toBe("not_applicable");
    expect(changes.value.firstHref).toBe(`/b/${ENTITY_ID}/changes`);
    const impacts = fake.requests.filter((request) => request.pathname === IMPACT);
    expect(new URL(impacts[1]?.url ?? "").searchParams.get("cursor")).toBe("p2");

    const none = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: "/v1/changes", body: ruleChangePageDto([ruleChangeDto({ citations: [] })]) },
      { path: IMPACT, body: changeImpactDto([{ entityId: OTHER_ENTITY, result: "applies" }]) },
    ]);
    const undecided = await getChanges(session, ENTITY_ID, null, { fetchImpl: none.fetchImpl });
    expect(undecided.ok && undecided.value.cards[0]?.applicability.value).toBe("not_decided");
  });

  it("gives up honestly after too many pages of clients, and shows a failed impact read", async () => {
    const endless = fakeFetch((request) => {
      if (request.pathname === `/v1/businesses/${ENTITY_ID}`)
        return jsonResponse(200, BUSINESS_DTO);
      if (request.pathname === "/v1/changes") {
        return jsonResponse(200, ruleChangePageDto([ruleChangeDto({ citations: [] })]));
      }
      return jsonResponse(
        200,
        changeImpactDto([{ entityId: OTHER_ENTITY, result: "applies" }], { next_cursor: "more" }),
      );
    });
    const far = await getChanges(session, ENTITY_ID, null, { fetchImpl: endless.fetchImpl });
    expect(far.ok && far.value.cards[0]?.applicability).toMatchObject({
      value: "unknown",
      failure: {
        message: "The firm has more clients than this page looks through for one change.",
      },
    });
    const failing = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: "/v1/changes", body: ruleChangePageDto([ruleChangeDto({ citations: [] })]) },
      { path: IMPACT, status: 503, problem: { title: "Example engine down" } },
    ]);
    const down = await getChanges(session, ENTITY_ID, null, { fetchImpl: failing.fetchImpl });
    expect(down.ok && down.value.cards[0]?.applicability.failure?.message).toBe(
      "Example engine down",
    );
  });

  it("passes on a missing business and a feed that failed", async () => {
    const missing = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} },
      { path: "/v1/changes", body: ruleChangePageDto([]) },
    ]);
    const gone = await getChanges(session, ENTITY_ID, null, { fetchImpl: missing.fetchImpl });
    expect(gone.ok ? null : gone.error.kind).toBe("not_found");
    const failing = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { path: "/v1/changes", status: 422, problem: { title: "Example bad cursor" } },
    ]);
    const bad = await getChanges(session, ENTITY_ID, "x", { fetchImpl: failing.fetchImpl });
    expect(bad.ok ? null : bad.error.kind).toBe("validation");
  });
});
