// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
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
import { getReviewItems } from "./queries";

const INTERNAL = "00000000-0000-4000-8000-0000000000ee";
const reviewer: ClientPrincipal = {
  userId: REVIEWER_ID,
  tenantId: INTERNAL,
  tenantKind: "internal",
  roles: ["reviewer"],
};
const analyst: ClientPrincipal = { ...reviewer, roles: ["analyst"] };
const OTHER_ITEM = "00000000-0000-4000-8000-00000000f0b2";

afterEach(() => {
  resetEnvCache();
});

describe("getReviewItems", () => {
  it("reads a status of the tenant's items, names each version once, and pages on", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/applicability-engine/review-items",
        body: {
          items: [reviewItemDto(), reviewItemDto({ item_id: OTHER_ITEM })],
          next_cursor: "next-1",
        },
      },
      {
        path: `/v1/rulebook/rule-versions/${RULE_VERSION_ID}`,
        body: ruleVersionDetailDto({ rule_version_id: RULE_VERSION_ID, version: 7 }),
      },
    ]);
    const read = await getReviewItems(
      reviewer,
      { tenantId: REVIEWED_TENANT_ID, status: "open", cursor: "after-1" },
      { fetchImpl: fake.fetchImpl },
    );
    if (!read.ok) throw new Error(read.error.message);
    expect(read.value.items.map((item) => [item.id, item.versionName])).toEqual([
      [REVIEW_ITEM_ID, "example_rule v7"],
      [OTHER_ITEM, "example_rule v7"],
    ]);
    expect(read.value.items[0]?.versionHref).toBe(`/admin/rulebook/versions/${RULE_VERSION_ID}`);
    expect(read.value.canResolve).toBe(true);
    expect(read.value.nextHref).toBe(`/admin/decisions?tenant=${REVIEWED_TENANT_ID}&cursor=next-1`);
    expect(read.value.firstHref).toBe(`/admin/decisions?tenant=${REVIEWED_TENANT_ID}`);
    expect(
      fake.requests.filter((request) => request.pathname.startsWith("/v1/rulebook")),
    ).toHaveLength(1);
    expect(fake.requests[0]?.url).toContain("status=open");
  });

  it("lists every status without a filter, reads for an analyst, and passes a refusal on", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/applicability-engine/review-items",
        body: { items: [resolvedItemDto()], next_cursor: null },
      },
      { path: `/v1/rulebook/rule-versions/${RULE_VERSION_ID}`, status: 404, problem: {} },
    ]);
    const read = await getReviewItems(
      analyst,
      { tenantId: REVIEWED_TENANT_ID, status: "all", cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    if (!read.ok) throw new Error(read.error.message);
    expect(fake.requests[0]?.url).not.toContain("status=");
    expect(read.value.canResolve).toBe(false);
    expect(read.value.items[0]?.versionName).toBe(RULE_VERSION_ID);
    expect(read.value.nextHref).toBeNull();
    expect(read.value.firstHref).toBeNull();
    const refused = await getReviewItems(
      analyst,
      { tenantId: REVIEWED_TENANT_ID, status: "open", cursor: null },
      {
        fetchImpl: fakeFetch([
          { path: "/v1/applicability-engine/review-items", status: 403, problem: {} },
        ]).fetchImpl,
      },
    );
    expect(!refused.ok && refused.error.kind).toBe("forbidden");
  });
});
