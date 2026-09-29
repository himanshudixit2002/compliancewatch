// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { PLAN_DTOS } from "@/test/billing-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { getBillingPage } from "./queries";

const owner: ClientPrincipal = {
  userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
  tenantId: "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b",
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getBillingPage", () => {
  it("reads the plans into their views, or passes a failure on", async () => {
    const page = await getBillingPage(owner, {
      fetchImpl: fakeFetch([{ path: "/v1/identity/billing/plans", body: PLAN_DTOS }]).fetchImpl,
    });
    expect(page.ok && page.value.plans.map((plan) => plan.price)).toEqual([
      "Rs 1,499.00",
      "Rs 0.00",
    ]);
    const failed = await getBillingPage(owner, {
      fetchImpl: fakeFetch([{ path: "/v1/identity/billing/plans", status: 503, problem: {} }])
        .fetchImpl,
    });
    expect(failed.ok).toBe(false);
  });
});
