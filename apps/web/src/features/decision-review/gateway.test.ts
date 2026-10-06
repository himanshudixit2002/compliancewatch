// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import {
  REVIEWED_TENANT_ID,
  REVIEWER_ID,
  REVIEW_ITEM_ID,
  resolvedItemDto,
  reviewItemDto,
} from "@/test/engine-admin-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { RULE_VERSION_ID } from "@/test/obligation-fixture";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import { decisionReviewGateway } from "./gateway";

const reviewer: ClientPrincipal = {
  userId: REVIEWER_ID,
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["reviewer"],
};

afterEach(() => {
  resetEnvCache();
});

describe("DecisionReviewGateway", () => {
  it("reads the looked-up tenant's items with its id as x-tenant-id, uncached", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/applicability-engine/review-items",
        body: { items: [reviewItemDto()], next_cursor: "next-1" },
      },
    ]);
    const gateway = decisionReviewGateway({
      session: reviewer,
      tenantId: REVIEWED_TENANT_ID,
      fetchImpl: fake.fetchImpl,
    });
    const page = await gateway.items({ status: "open", limit: 20, cursor: "after-1" });
    expect(page.ok && page.value.items[0]?.id).toBe(REVIEW_ITEM_ID);
    expect(page.ok && page.value.nextCursor).toBe("next-1");
    expect(fake.requests[0]?.url).toBe(
      "http://localhost:8004/v1/applicability-engine/review-items?limit=20&status=open&cursor=after-1",
    );
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(REVIEWED_TENANT_ID);
    expect(fake.requests[0]?.cache).toBe("no-store");
  });

  it("settles an item with the reviewer the caller names, and reads a version without a tenant", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: `/v1/applicability-engine/review-items/${REVIEW_ITEM_ID}/resolve`,
        body: resolvedItemDto(),
      },
      {
        path: `/v1/rulebook/rule-versions/${RULE_VERSION_ID}`,
        body: ruleVersionDetailDto({ rule_version_id: RULE_VERSION_ID }),
      },
    ]);
    const gateway = decisionReviewGateway({
      session: reviewer,
      tenantId: REVIEWED_TENANT_ID,
      fetchImpl: fake.fetchImpl,
    });
    const settled = await gateway.resolve(
      REVIEW_ITEM_ID,
      { resolution: "applies", note: "Example note" },
      REVIEWER_ID,
    );
    expect(settled.ok && settled.value.status).toBe("resolved");
    expect(fake.requests[0]?.body).toEqual({
      resolution: "applies",
      note: "Example note",
      resolved_by: REVIEWER_ID,
    });
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(REVIEWED_TENANT_ID);
    const version = await gateway.version(RULE_VERSION_ID);
    expect(version.ok && version.value.ruleKey).toBe("example_rule");
    expect(fake.requests[1]?.headers[TENANT_HEADER]).toBeUndefined();
  });
});
