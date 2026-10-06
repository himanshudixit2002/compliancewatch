// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import {
  REGISTRATION_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TENANT_ID,
} from "@/test/business-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { getNodeReview } from "./queries";

const analyst: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b1",
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["analyst"],
};

const LOOKUP = { tenantId: TENANT_ID, nodeId: REGISTRATION_ID, fy: "2000-01" };

afterEach(() => {
  resetEnvCache();
});

describe("getNodeReview", () => {
  it("puts the node, its tasks, its snapshot and the ontology's words together", async () => {
    const fake = fakeFetch([
      { path: `/v1/profile/nodes/${REGISTRATION_ID}`, body: REGISTRATION_DTO },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`, body: [REVIEW_TASK_DTO] },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/snapshot`, body: SNAPSHOT_DTO },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
    ]);
    const review = await getNodeReview(analyst, LOOKUP, { fetchImpl: fake.fetchImpl });
    expect(review.ok && review.value?.node.name).toBe("Example registration");
    expect(review.ok && review.value?.tasks).toHaveLength(1);
    expect(review.ok && review.value?.ontologyMissing).toBe(false);
  });

  it("answers null for a node the tenant does not hold, and passes other failures on", async () => {
    const missing = fakeFetch([
      { path: `/v1/profile/nodes/${REGISTRATION_ID}`, status: 404, problem: { title: "Gone" } },
    ]);
    expect(await getNodeReview(analyst, LOOKUP, { fetchImpl: missing.fetchImpl })).toEqual({
      ok: true,
      value: null,
    });
    const failing = fakeFetch([
      { path: `/v1/profile/nodes/${REGISTRATION_ID}`, body: REGISTRATION_DTO },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`, body: [] },
      {
        path: `/v1/profile/nodes/${REGISTRATION_ID}/snapshot`,
        status: 422,
        problem: { title: "Example refusal" },
      },
      { path: "/v1/ontology", status: 503, problem: { title: "Example outage" } },
    ]);
    const review = await getNodeReview(analyst, LOOKUP, { fetchImpl: failing.fetchImpl });
    expect(!review.ok && review.error.message).toBe("Example refusal");
  });

  it("words the page as stored when only the ontology fails", async () => {
    const fake = fakeFetch([
      { path: `/v1/profile/nodes/${REGISTRATION_ID}`, body: REGISTRATION_DTO },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`, body: [] },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/snapshot`, body: SNAPSHOT_DTO },
      { path: "/v1/ontology", status: 503, problem: { title: "Example outage" } },
    ]);
    const review = await getNodeReview(analyst, LOOKUP, { fetchImpl: fake.fetchImpl });
    expect(review.ok && review.value?.ontologyMissing).toBe(true);
  });
});
