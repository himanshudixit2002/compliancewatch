// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO, DEMO_GSTIN } from "@/test/business-fixture";
import { CHANGED_VERSION_ID, changeImpactDto } from "@/test/change-fixture";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import { getChangeImpact } from "./queries";

const FIRM = "00000000-0000-4000-8000-00000000c0aa";
const caAdmin: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-00000000c0ab",
  tenantId: FIRM,
  tenantKind: "ca_firm",
  roles: ["ca_admin"],
};
const IMPACT = `/v1/changes/${CHANGED_VERSION_ID}/impact`;
const VERSION = `/v1/rulebook/rule-versions/${CHANGED_VERSION_ID}`;
const OTHER_CLIENT = "00000000-0000-4000-8000-0000000000e9";

afterEach(() => {
  resetEnvCache();
});

describe("getChangeImpact", () => {
  it("names the change and its clients, counts, and gathers the affected businesses for the card", async () => {
    const fake = fakeFetch((request) => {
      if (request.pathname === VERSION) {
        return jsonResponse(
          200,
          ruleVersionDetailDto({
            rule_version_id: CHANGED_VERSION_ID,
            version: 2,
            title: "Example rule 2",
            status: "published",
          }),
        );
      }
      if (request.pathname === `/v1/businesses/${ENTITY_ID}`)
        return jsonResponse(200, BUSINESS_DTO);
      if (request.pathname === `/v1/businesses/${OTHER_CLIENT}`) return problemResponse(404);
      if (request.pathname === IMPACT) {
        const url = new URL(request.url);
        if (url.searchParams.get("limit") === "200") {
          // The walk for the card: two pages of affected clients.
          return url.searchParams.get("cursor") === null
            ? jsonResponse(200, changeImpactDto([{ result: "applies" }], { next_cursor: "walk-2" }))
            : jsonResponse(
                200,
                changeImpactDto([
                  { entityId: OTHER_CLIENT, businessId: OTHER_CLIENT, result: "applies" },
                ]),
              );
        }
        return jsonResponse(
          200,
          changeImpactDto(
            [
              { result: "applies" },
              { entityId: OTHER_CLIENT, businessId: OTHER_CLIENT, result: "applies" },
            ],
            { counts: { applies: 2, not_applicable: 5, unsure: 0 }, next_cursor: "page-2" },
          ),
        );
      }
      return problemResponse(404);
    });
    const read = await getChangeImpact(
      caAdmin,
      CHANGED_VERSION_ID,
      { result: "applies", cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    if (!read.ok) throw new Error(read.error.message);
    expect(read.value).toMatchObject({
      name: "example_rule v2",
      title: "Example rule 2",
      status: "Published",
      counts: { applies: "2", notApplicable: "5", unsure: "0", total: "7" },
      filter: "applies",
      nextHref: `/changes/${CHANGED_VERSION_ID}/impact?cursor=page-2`,
      firstHref: null,
      targetsCut: false,
    });
    expect(read.value.fanOut).toMatch(/^The engine has no fan-out/);
    expect(read.value.clients.map((client) => client.name)).toEqual([
      "Example business (ABCDE1234F)",
      OTHER_CLIENT,
    ]);
    expect(read.value.targets).toEqual([
      {
        businessId: REGISTRATION_ID,
        label: `Example business: GSTIN ${DEMO_GSTIN}, Example registration`,
      },
      { businessId: OTHER_CLIENT, label: OTHER_CLIENT },
    ]);
    const displayed = fake.requests.find(
      (request) => request.pathname === IMPACT && request.url.includes("limit=50"),
    );
    expect(displayed?.url).toContain("result=applies");
  });

  it("lists every result without a filter, says when the walk stopped short, and fails on the rulebook", async () => {
    const fake = fakeFetch((request) => {
      if (request.pathname === VERSION) {
        return jsonResponse(200, ruleVersionDetailDto({ rule_version_id: CHANGED_VERSION_ID }));
      }
      if (request.pathname === IMPACT) {
        const url = new URL(request.url);
        return url.searchParams.get("limit") === "200"
          ? problemResponse(503)
          : jsonResponse(200, changeImpactDto([], { next_cursor: null }));
      }
      return problemResponse(404);
    });
    const read = await getChangeImpact(
      caAdmin,
      CHANGED_VERSION_ID,
      { result: "all", cursor: "page-2" },
      { fetchImpl: fake.fetchImpl },
    );
    if (!read.ok) throw new Error(read.error.message);
    expect(read.value.clients).toEqual([]);
    expect(read.value.targets).toEqual([]);
    expect(read.value.targetsCut).toBe(true);
    expect(read.value.firstHref).toBe(`/changes/${CHANGED_VERSION_ID}/impact?result=all`);
    const displayed = fake.requests.find((request) => request.url.includes("limit=50"));
    expect(displayed?.url).not.toContain("result=");
    const unknown = await getChangeImpact(
      caAdmin,
      CHANGED_VERSION_ID,
      { result: "applies", cursor: null },
      { fetchImpl: fakeFetch([{ path: IMPACT, body: changeImpactDto([]) }]).fetchImpl },
    );
    expect(!unknown.ok && unknown.error.kind).toBe("not_found");
  });

  it("stops the walk for the card after five pages and keeps at most 500 businesses", async () => {
    let walked = 0;
    const fake = fakeFetch((request) => {
      if (request.pathname === VERSION) {
        return jsonResponse(200, ruleVersionDetailDto({ rule_version_id: CHANGED_VERSION_ID }));
      }
      if (request.pathname === IMPACT) {
        const url = new URL(request.url);
        if (url.searchParams.get("limit") !== "200") return jsonResponse(200, changeImpactDto([]));
        walked += 1;
        const results = Array.from({ length: 120 }, (_, index) => ({
          entityId: `00000000-0000-4000-8000-${String(walked * 1000 + index).padStart(12, "0")}`,
          businessId: `00000000-0000-4000-9000-${String(walked * 1000 + index).padStart(12, "0")}`,
          result: "applies" as const,
        }));
        return jsonResponse(200, changeImpactDto(results, { next_cursor: `walk-${walked + 1}` }));
      }
      return problemResponse(404);
    });
    const read = await getChangeImpact(
      caAdmin,
      CHANGED_VERSION_ID,
      { result: "applies", cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    if (!read.ok) throw new Error(read.error.message);
    expect(walked).toBe(5);
    expect(read.value.targets).toHaveLength(500);
    expect(read.value.targetsCut).toBe(true);
  });
});
