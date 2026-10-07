// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { PLAN_DTOS, subscriptionDto } from "@/test/billing-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { startSubscription } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const IDLE = { status: "idle" } as const;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
    tenantId: TENANT,
    tenantKind: "business",
    roles: ["owner"],
    displayName: "Example owner",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const FORM_UUID = "3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6a";
const VALID = {
  plan_key: "example_monthly",
  email: "owner@example.com",
  name: "Example Traders",
  [IDEMPOTENCY_KEY_FIELD]: FORM_UUID,
};

/** The identity service with the provider the test names: none answers 503, memory 201. */
function identity(provider: "none" | "memory", options: { failPlans?: boolean } = {}) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.pathname === "/v1/identity/billing/plans") {
      return options.failPlans === true
        ? problemResponse(503, { title: "Identity is unavailable" })
        : jsonResponse(200, PLAN_DTOS);
    }
    if (request.pathname === "/v1/identity/billing/subscriptions") {
      return provider === "none"
        ? problemResponse(503, {
            type: "urn:compliancewatch:problem:billing-disabled",
            title: "Billing provider disabled",
            detail: "billing provider disabled: set CW_BILLING_PROVIDER and its keys",
          })
        : jsonResponse(
            201,
            subscriptionDto({ provider_subscription_id: "sub_mem_1", checkout_url: "" }),
          );
    }
    return problemResponse(404);
  });
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.clearAllMocks();
});

describe("startSubscription", () => {
  it("reports billing-disabled as the service's problem when no provider is connected", async () => {
    await signedInAs();
    const fake = identity("none");
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await startSubscription(IDLE, form(VALID));
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(state.problem).toMatchObject({
      type: "urn:compliancewatch:problem:billing-disabled",
      title: "Billing provider disabled",
    });
    expect(state.problem?.correlationId).toMatch(/^[0-9a-f-]{36}$/);
    const post = fake.requests.find((request) => request.method === "POST");
    expect(post?.headers["x-tenant-id"]).toBe(TENANT);
    expect(post?.headers["idempotency-key"]).toBe(FORM_UUID);
    expect(post?.body).toEqual({
      plan_key: "example_monthly",
      email: "owner@example.com",
      name: "Example Traders",
    });
  });

  it("returns the subscription the memory provider starts, without a checkout page", async () => {
    await signedInAs({ tenantKind: "ca_firm", roles: ["ca_admin"] });
    vi.stubGlobal("fetch", identity("memory").fetchImpl);
    expect(await startSubscription(IDLE, form(VALID))).toEqual({
      status: "ok",
      value: {
        planName: "Example monthly plan",
        status: "Created",
        providerSubscriptionId: "sub_mem_1",
        startedAt: "1 Jan 2000, 5:30 am IST",
        checkoutUrl: null,
      },
    });
  });

  it("names the fields to fix before starting anything", async () => {
    await signedInAs();
    const fake = identity("memory");
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await startSubscription(IDLE, form({ plan_key: "other", email: "", name: "" }));
    expect(state).toEqual({
      status: "error",
      fieldErrors: {
        plan_key: ["Choose one of the plans listed."],
        email: ["Enter the billing email."],
        name: ["Enter the billing name."],
      },
    });
    expect(fake.requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("reports a failed plans read", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", identity("memory", { failPlans: true }).fetchImpl);
    const state = await startSubscription(IDLE, form(VALID));
    expect(state.status === "error" && state.problem?.title).toBe("Identity is unavailable");
  });

  it("sends staff to the forbidden page and a visitor to sign in", async () => {
    await expect(startSubscription(IDLE, form(VALID))).rejects.toMatchObject({
      href: "/sign-in?next=%2Fsettings%2Fbilling",
    });
    await signedInAs({ roles: ["staff"] });
    await expect(startSubscription(IDLE, form(VALID))).rejects.toMatchObject({
      href: "/forbidden",
    });
  });
});
