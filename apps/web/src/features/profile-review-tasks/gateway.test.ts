// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
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
import { profileReviewGateway } from "./gateway";

const analyst: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b1",
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["analyst"],
};

afterEach(() => {
  resetEnvCache();
});

describe("ProfileReviewGateway", () => {
  it("reads the node, its tasks and its snapshot as the looked-up tenant, uncached", async () => {
    const fake = fakeFetch([
      { path: `/v1/profile/nodes/${REGISTRATION_ID}`, body: REGISTRATION_DTO },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`, body: [REVIEW_TASK_DTO] },
      { path: `/v1/profile/nodes/${REGISTRATION_ID}/snapshot`, body: SNAPSHOT_DTO },
    ]);
    const gateway = profileReviewGateway({
      session: analyst,
      tenantId: TENANT_ID,
      fetchImpl: fake.fetchImpl,
    });
    const node = await gateway.node(REGISTRATION_ID);
    const tasks = await gateway.reviewTasks(REGISTRATION_ID);
    const snapshot = await gateway.snapshot(REGISTRATION_ID, "2000-01");
    expect(node.ok && node.value.name).toBe("Example registration");
    expect(tasks.ok && tasks.value).toHaveLength(1);
    expect(snapshot.ok && snapshot.value.version).toBe(8);
    expect(fake.requests[2]?.url).toBe(
      `http://localhost:8002/v1/profile/nodes/${REGISTRATION_ID}/snapshot?fy=2000-01`,
    );
    for (const request of fake.requests) {
      expect(request.headers[TENANT_HEADER]).toBe(TENANT_ID);
      expect(request.cache).toBe("no-store");
    }
  });
});
