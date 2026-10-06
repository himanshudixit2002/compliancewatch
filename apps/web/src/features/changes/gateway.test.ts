// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO } from "@/test/business-fixture";
import {
  CHANGED_VERSION_ID,
  changeImpactDto,
  ruleChangeDto,
  ruleChangePageDto,
} from "@/test/change-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { CLAUSE_ID, DOCUMENT_ID, ENTITY_ID, TENANT_ID, USER_ID } from "@/test/obligation-fixture";
import { changesGateway } from "./gateway";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  resetEnvCache();
});

describe("ChangesGateway", () => {
  it("reads the feed without a tenant and the impact with one, neither cached", async () => {
    const fake = fakeFetch([
      { path: "/v1/changes", body: ruleChangePageDto([ruleChangeDto()], "next-1") },
      { path: `/v1/changes/${CHANGED_VERSION_ID}/impact`, body: changeImpactDto() },
    ]);
    const gateway = changesGateway({ session, fetchImpl: fake.fetchImpl });
    const feed = await gateway.feed({ limit: 20, cursor: "after-1" });
    expect(feed.ok && feed.value.items[0]?.title).toBe("Example rule 2");
    const impact = await gateway.impact(CHANGED_VERSION_ID, { limit: 200 });
    expect(impact.ok && impact.value.clients[0]?.entityId).toBe(ENTITY_ID);
    const [feedRequest, impactRequest] = fake.requests;
    expect(feedRequest?.url).toBe("http://localhost:8003/v1/changes?limit=20&cursor=after-1");
    expect(feedRequest?.headers[TENANT_HEADER]).toBeUndefined();
    expect(feedRequest?.cache).toBe("no-store");
    expect(impactRequest?.url).toBe(
      `http://localhost:8004/v1/changes/${CHANGED_VERSION_ID}/impact?limit=200`,
    );
    expect(impactRequest?.headers[TENANT_HEADER]).toBe(TENANT_ID);
    expect(impactRequest?.cache).toBe("no-store");
  });

  it("reads a cited clause under its tag and the business from the profile service", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/rulebook/clauses/${CLAUSE_ID}`,
        body: {
          clause_id: CLAUSE_ID,
          document_id: DOCUMENT_ID,
          clause_ref: "en.p2",
          ordinal: 2,
          page: null,
          text: "Example clause",
          regulator: "Example regulator",
          doc_type: "circular",
          external_ref: "Example 1/2000",
          title: "Example document title",
          url: "https://example.com/a.pdf",
          language: "en",
          published_at: null,
        },
      },
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
    ]);
    const gateway = changesGateway({ session, fetchImpl: fake.fetchImpl });
    expect((await gateway.clause(CLAUSE_ID)).ok).toBe(true);
    expect(fake.requests[0]?.next?.tags).toEqual([`rulebook:clause:${CLAUSE_ID}`]);
    const business = await gateway.business(ENTITY_ID);
    expect(business.ok && business.value.name).toBe("Example business");
    expect(fake.requests[1]?.headers[TENANT_HEADER]).toBe(TENANT_ID);
  });
});
