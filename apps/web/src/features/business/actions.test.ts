// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import {
  BUSINESS_CREATED_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { createBusiness } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const IDEMPOTENCY_KEY = "00000000-0000-4000-8000-00000000abcd";
const IDLE = { status: "idle" } as const;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: USER_ID,
    tenantId: TENANT_ID,
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

const VALID = {
  gstin: "29abcde1234f1z5",
  name: "Example business",
  idempotency_key: IDEMPOTENCY_KEY,
};

function profile(options: { create?: Response; ontology?: Response } = {}) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.method === "POST" && request.pathname === "/v1/businesses") {
      return options.create ?? jsonResponse(201, BUSINESS_CREATED_DTO);
    }
    if (request.method === "GET" && request.pathname === "/v1/ontology") {
      return options.ontology ?? jsonResponse(200, ONTOLOGY_DTO);
    }
    return problemResponse(404);
  });
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
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

describe("createBusiness", () => {
  it("creates the business with the form's key and returns what the lookup gave", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state.status).toBe("ok");
    const create = fake.requests.find((request) => request.method === "POST");
    expect(create?.headers["idempotency-key"]).toBe(IDEMPOTENCY_KEY);
    expect(create?.headers["x-tenant-id"]).toBe(TENANT_ID);
    expect(create?.body).toEqual({ name: "Example business", gstin: DEMO_GSTIN });
    if (state.status !== "ok") return;
    expect(state.value).toMatchObject({
      businessId: ENTITY_ID,
      gstin: DEMO_GSTIN,
      created: true,
      nextHref: `/onboarding/${ENTITY_ID}/questions`,
    });
    expect(revalidatePath).toHaveBeenCalledWith("/businesses");
  });

  it("refuses a malformed form before calling the service", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form({ gstin: "29ABC", name: "" }));
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(Object.keys(state.fieldErrors ?? {})).toEqual(["gstin", "name"]);
    expect(fake.requests).toEqual([]);
  });

  it("returns the service's problem, field errors included", async () => {
    await signedInAs();
    const fake = profile({
      create: problemResponse(422, {
        title: "Request invalid",
        errors: [{ loc: ["body", "name"], msg: "Example message.", type: "value_error" }],
      }),
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(state.problem?.title).toBe("Request invalid");
    expect(state.fieldErrors?.name).toEqual(["Example message."]);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("still returns the created business when the ontology cannot be read", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", profile({ ontology: problemResponse(503) }).fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state.status).toBe("ok");
  });

  it("runs the screen's gate: a compliance lead is sent to the forbidden page", async () => {
    await signedInAs({ roles: ["compliance_lead"] });
    vi.stubGlobal("fetch", profile().fetchImpl);
    await expect(createBusiness(IDLE, form(VALID))).rejects.toThrow("redirect /forbidden");
  });
});
