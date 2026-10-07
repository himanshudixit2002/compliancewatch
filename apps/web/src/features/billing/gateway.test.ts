// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { PLAN_DTOS, subscriptionDto } from "@/test/billing-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { billingGateway } from "./gateway";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const REQUEST_UUID = "0b7c8d9e-1f2a-4b3c-8d4e-5f6a7b8c9d0e";
const owner: ClientPrincipal = {
  userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("BillingGateway", () => {
  it("keeps the plans under their tag for five minutes", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/identity/billing/plans", body: PLAN_DTOS },
    ]);
    const plans = await billingGateway({ session: owner, fetchImpl: fake.fetchImpl }).plans();
    expect(plans.ok && plans.value.map((plan) => plan.key)).toEqual([
      "example_monthly",
      "example_yearly",
    ]);
    expect(fake.requests[0]?.url).toBe("http://localhost:8001/v1/identity/billing/plans");
    expect(fake.requests[0]?.next).toEqual({ revalidate: 300, tags: ["identity:plans"] });
  });

  it("starts a subscription for the session's tenant", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/billing/subscriptions",
        status: 201,
        body: subscriptionDto(),
      },
    ]);
    const started = await billingGateway({ session: owner, fetchImpl: fake.fetchImpl }).subscribe(
      { planKey: "example_monthly", email: "owner@example.com", name: "Example Traders" },
      { "Idempotency-Key": REQUEST_UUID },
    );
    expect(started.ok && started.value.providerSubscriptionId).toBe("sub_example_1");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(fake.requests[0]?.headers["idempotency-key"]).toBe(REQUEST_UUID);
    expect(fake.requests[0]?.body).toEqual({
      plan_key: "example_monthly",
      email: "owner@example.com",
      name: "Example Traders",
    });
  });

  it("passes the billing-disabled problem on as unavailable", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/billing/subscriptions",
        status: 503,
        problem: {
          type: "urn:compliancewatch:problem:billing-disabled",
          title: "Billing provider disabled",
        },
      },
    ]);
    const started = await billingGateway({ session: owner, fetchImpl: fake.fetchImpl }).subscribe(
      { planKey: "example_monthly", email: "owner@example.com", name: "Example Traders" },
      { "Idempotency-Key": REQUEST_UUID },
    );
    expect(!started.ok && started.error.kind).toBe("unavailable");
  });
});
