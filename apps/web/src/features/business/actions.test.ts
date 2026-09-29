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
  BUSINESS_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  REGISTRATION_ID,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { answerQuestion, createBusiness, revisitUnsure } from "./actions";
import { skipCookieName, skipKey } from "./model/questions";

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

function profile(options: { create?: Response; ontology?: Response; patch?: Response } = {}) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.method === "POST" && request.pathname === "/v1/businesses") {
      return options.create ?? jsonResponse(201, BUSINESS_CREATED_DTO);
    }
    if (request.method === "PATCH" && request.pathname === `/v1/businesses/${ENTITY_ID}`) {
      return options.patch ?? jsonResponse(200, BUSINESS_DTO);
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

const ANSWER = {
  business_id: ENTITY_ID,
  node_id: REGISTRATION_ID,
  key: "example_flag",
  as_of_fy: "",
};

describe("answerQuestion", () => {
  it("stores a value on the checklist's node and moves on, naming what was saved", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(
      answerQuestion(IDLE, form({ ...ANSWER, state: "known", value: "true" })),
    ).rejects.toThrow(`redirect /onboarding/${ENTITY_ID}/questions?saved=example_flag`);
    const patch = fake.requests.find((request) => request.method === "PATCH");
    expect(patch?.body).toEqual({
      changes: [{ key: "example_flag", state: "known", value: true, node_id: REGISTRATION_ID }],
    });
    expect(fakeCookies.written(skipCookieName(ENTITY_ID))).toBeUndefined();
    expect(revalidatePath).toHaveBeenCalledWith(`/onboarding/${ENTITY_ID}/questions`);
    expect(revalidatePath).toHaveBeenCalledWith(`/onboarding/${ENTITY_ID}/done`);
  });

  it("puts a Not sure answer on the skip list and takes it off again on a later answer", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", profile().fetchImpl);
    await expect(answerQuestion(IDLE, form({ ...ANSWER, state: "unsure" }))).rejects.toThrow(
      "redirect",
    );
    const item = skipKey(REGISTRATION_ID, "example_flag");
    expect(fakeCookies.get(skipCookieName(ENTITY_ID))?.value).toBe(JSON.stringify([item]));
    await expect(
      answerQuestion(IDLE, form({ ...ANSWER, state: "not_applicable" })),
    ).rejects.toThrow("redirect");
    expect(fakeCookies.get(skipCookieName(ENTITY_ID))?.value).toBe("[]");
  });

  it("refuses a tampered form, an unknown attribute and a value of the wrong shape", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const tampered = await answerQuestion(IDLE, form({ ...ANSWER, node_id: "x", state: "known" }));
    expect(tampered.status === "error" && tampered.formErrors?.[0]).toMatch(/Reload the page/);
    const unknown = await answerQuestion(
      IDLE,
      form({ ...ANSWER, key: "no_such_key", state: "unsure" }),
    );
    expect(unknown.status === "error" && unknown.formErrors?.[0]).toMatch(/not in the ontology/);
    const shape = await answerQuestion(IDLE, form({ ...ANSWER, state: "known", value: "maybe" }));
    expect(shape).toEqual({
      status: "error",
      fieldErrors: { value: ["Choose one of the options."] },
    });
    expect(fake.requests.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("puts the service's value error on the control and the rest on the form", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      profile({
        patch: problemResponse(422, {
          title: "Invalid attribute value",
          errors: [
            { loc: ["body", "changes", 0, "value"], msg: "Example value message.", type: "x" },
            { loc: ["body", "changes", 0, "as_of_fy"], msg: "Example year message.", type: "x" },
          ],
        }),
      }).fetchImpl,
    );
    const state = await answerQuestion(IDLE, form({ ...ANSWER, state: "known", value: "true" }));
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "Invalid attribute value" },
      fieldErrors: { value: ["Example value message."] },
      formErrors: ["Example year message."],
    });
  });

  it("returns a problem without field errors as it came", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      profile({ patch: problemResponse(404, { title: "Not found" }) }).fetchImpl,
    );
    const state = await answerQuestion(IDLE, form({ ...ANSWER, state: "unsure" }));
    expect(state).toEqual({
      status: "error",
      problem: expect.objectContaining({ title: "Not found" }),
    });
  });

  it("reports an unreadable ontology before storing anything", async () => {
    await signedInAs();
    const fake = profile({ ontology: problemResponse(503, { title: "Profile is down" }) });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await answerQuestion(IDLE, form({ ...ANSWER, state: "unsure" }));
    expect(state.status === "error" && state.problem?.title).toBe("Profile is down");
  });
});

describe("revisitUnsure", () => {
  it("forgets the skip list and returns to the questions", async () => {
    await signedInAs();
    fakeCookies.set(
      skipCookieName(ENTITY_ID),
      JSON.stringify([skipKey(ENTITY_ID, "example_count")]),
    );
    await expect(revisitUnsure(form({ business_id: ENTITY_ID }))).rejects.toThrow(
      `redirect /onboarding/${ENTITY_ID}/questions`,
    );
    expect(fakeCookies.get(skipCookieName(ENTITY_ID))).toBeUndefined();
  });

  it("does nothing for a malformed business id", async () => {
    await signedInAs();
    await expect(revisitUnsure(form({ business_id: "x" }))).resolves.toBeUndefined();
    expect(redirect).not.toHaveBeenCalled();
  });
});
