// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { analyticsNoticeVersion } from "@/server/analytics";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { readLegalVersions } from "@/server/legal";
import { encryptSession } from "@/server/session";
import {
  BUSINESS_CREATED_DTO,
  BUSINESS_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  LOCATION_DTO,
  LOCATION_ID,
  REGISTRATION_ID,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import {
  addLocation,
  answerQuestion,
  createBusiness,
  revisitUnsure,
  saveAttribute,
  searchBusinesses,
} from "./actions";
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

const LEGAL = readLegalVersions();
/** The required consents granted at the Version lines this build ships. */
const REQUIRED_GRANTED = [
  grantedState("terms", `terms-of-service@${LEGAL["terms-of-service"].version}`),
  grantedState("privacy_notice", `privacy-notice@${LEGAL["privacy-notice"].version}`),
  grantedState("profile_processing", `privacy-notice@${LEGAL["privacy-notice"].version}`),
];

function profile(
  options: {
    create?: Response;
    ontology?: Response;
    patch?: Response;
    list?: Response;
    location?: Response;
    business?: Response;
    consents?: Response;
  } = {},
) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.method === "GET" && request.pathname === "/v1/identity/consents") {
      return options.consents ?? jsonResponse(200, summaryDto(REQUIRED_GRANTED));
    }
    if (request.method === "GET" && request.pathname === "/v1/businesses") {
      return options.list ?? jsonResponse(200, { items: [], next_cursor: null });
    }
    if (request.method === "GET" && request.pathname === `/v1/businesses/${ENTITY_ID}`) {
      return options.business ?? jsonResponse(200, BUSINESS_DTO);
    }
    if (request.method === "POST" && request.pathname === "/v1/profile/locations") {
      return options.location ?? jsonResponse(201, LOCATION_DTO);
    }
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

  it("creates nothing for a person without the required consents on file", async () => {
    // A user posting the action directly, without the consent step's records: the page would
    // not have offered the form, and the profile service does not check consents itself.
    await signedInAs({ tenantKind: "ca_firm", roles: ["ca_staff"] });
    const fake = profile({
      consents: jsonResponse(
        200,
        summaryDto([
          grantedState("terms", `terms-of-service@${LEGAL["terms-of-service"].version}`),
          grantedState("analytics", `privacy-notice@${LEGAL["privacy-notice"].version}`),
        ]),
      ),
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state).toEqual({
      status: "error",
      formErrors: [
        "A business profile is processed on the strength of your consents. Record them on the consent step, then come back here.",
      ],
    });
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      "GET /v1/identity/consents",
    ]);
    expect(fake.requests[0]?.url).toContain(`subject=${USER_ID}`);
  });

  it("creates nothing when the consents cannot be read, and says why", async () => {
    await signedInAs();
    const fake = profile({ consents: problemResponse(503, { title: "Identity is unavailable" }) });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state.status === "error" && state.problem?.title).toBe("Identity is unavailable");
    expect(fake.requests.some((request) => request.pathname === "/v1/businesses")).toBe(false);
  });
});

const ANSWER = {
  business_id: ENTITY_ID,
  node_id: REGISTRATION_ID,
  key: "example_flag",
  as_of_fy: "",
};

describe("closed onboarding", () => {
  it("adds no business in production while the legal documents are drafts", async () => {
    vi.stubEnv("CW_WEB_ENV", "prod");
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await createBusiness(IDLE, form(VALID));
    expect(state).toEqual({
      status: "error",
      formErrors: [
        "Onboarding is closed until the legal documents are reviewed; nothing was recorded.",
      ],
    });
    expect(fake.requests).toHaveLength(0);
  });
});

describe("product analytics", () => {
  beforeEach(async () => {
    await resetFlagReader();
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ANALYTICS_ENABLED", "true");
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await resetFlagReader();
  });

  /** The profile service, and identity answering the analytics consent at the current notice. */
  function servicesWithConsent() {
    const notice = analyticsNoticeVersion(readLegalVersions());
    const identity = fakeFetch([
      {
        method: "GET",
        path: "/v1/identity/consents",
        body: summaryDto([...REQUIRED_GRANTED, grantedState("analytics", notice)]),
      },
    ]);
    const services = profile();
    return (input: Request, init?: RequestInit) =>
      new URL(input.url).pathname === "/v1/identity/consents"
        ? identity.fetchImpl(input, init)
        : services.fetchImpl(input, init);
  }

  function productEvents(log: { mock: { calls: unknown[][] } }): unknown[] {
    return log.mock.calls
      .map((call) => JSON.parse(String(call[0])) as { event?: string })
      .filter((line) => line.event === "product_event");
  }

  it("emits the business step and each answer when the flag is on and analytics is consented", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await signedInAs();
    vi.stubGlobal("fetch", servicesWithConsent());
    expect((await createBusiness(IDLE, form(VALID))).status).toBe("ok");
    await expect(answerQuestion(IDLE, form({ ...ANSWER, state: "unsure" }))).rejects.toThrow(
      "redirect",
    );
    expect(productEvents(log)).toEqual([
      expect.objectContaining({
        name: "onboarding_step_completed",
        tenant_id: TENANT_ID,
        user_id: USER_ID,
        properties: { step: "business", created: true, looked_up: false },
      }),
      expect.objectContaining({
        name: "onboarding_step_completed",
        properties: { step: "question", attribute: "example_flag", state: "unsure" },
      }),
    ]);
  });
});

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

describe("searchBusinesses", () => {
  it("reads the page the form asks for, the term in the body", async () => {
    await signedInAs({ tenantKind: "ca_firm", roles: ["ca_admin"] });
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await searchBusinesses(
      { status: "idle" },
      form({ q: "example", cursor: "c1", page: "2" }),
    );
    expect(state).toEqual({
      status: "ok",
      value: { q: "example", page: 2, rows: [], nextCursor: null },
    });
    expect(fake.requests[0]?.url).toContain("q=example");
    expect(fake.requests[0]?.url).toContain("cursor=c1");
  });

  it("refuses a term that is too long and passes on a failed read", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", profile({ list: problemResponse(503, { title: "Down" }) }).fetchImpl);
    const long = await searchBusinesses({ status: "idle" }, form({ q: "x".repeat(101) }));
    expect(long.status === "error" && long.formErrors?.[0]).toMatch(/at most 100/);
    const failed = await searchBusinesses({ status: "idle" }, form({ q: "" }));
    expect(failed.status === "error" && failed.problem?.title).toBe("Down");
  });
});

describe("saveAttribute", () => {
  const CHANGE = { ...ANSWER, key: "example_kind", state: "known", value: "first" };

  it("stores the answer and says which version the node is at", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await saveAttribute(IDLE, form(CHANGE));
    expect(state).toEqual({
      status: "ok",
      value: undefined,
      message: "Saved; the profile is now at version 3.",
    });
    expect(fake.requests.find((request) => request.method === "PATCH")?.body).toEqual({
      changes: [{ key: "example_kind", state: "known", value: "first", node_id: REGISTRATION_ID }],
    });
    expect(revalidatePath).toHaveBeenCalledWith(`/b/${ENTITY_ID}/attributes`);
    expect(revalidatePath).toHaveBeenCalledWith(`/b/${ENTITY_ID}/snapshot`);
    const entity = await saveAttribute(
      IDLE,
      form({ ...CHANGE, node_id: ENTITY_ID, key: "example_count", value: "12" }),
    );
    expect(entity.status === "ok" && entity.message).toBe(
      "Saved; the profile is now at version 5.",
    );
    const location = await saveAttribute(
      IDLE,
      form({ ...CHANGE, node_id: LOCATION_ID, key: "example_note", value: "Example" }),
    );
    expect(location.status === "ok" && location.message).toBe("Saved.");
  });

  it("refuses a reader, a tampered form, an unknown key and a bad value", async () => {
    await signedInAs({ roles: ["compliance_lead"] });
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const reader = await saveAttribute(IDLE, form(CHANGE));
    expect(reader.status === "error" && reader.formErrors?.[0]).toMatch(/not change it/);
    await signedInAs();
    const tampered = await saveAttribute(IDLE, form({ ...CHANGE, business_id: "x" }));
    expect(tampered.status).toBe("error");
    const unknown = await saveAttribute(IDLE, form({ ...CHANGE, key: "no_such_key" }));
    expect(unknown.status === "error" && unknown.formErrors?.[0]).toMatch(/not in the ontology/);
    const bad = await saveAttribute(IDLE, form({ ...CHANGE, value: "nope" }));
    expect(bad.status === "error" && bad.fieldErrors?.value).toEqual([
      "Choose one of the options.",
    ]);
    expect(fake.requests.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("passes on the service's refusal and an unreadable ontology", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", profile({ patch: problemResponse(404, { title: "Gone" }) }).fetchImpl);
    const refused = await saveAttribute(IDLE, form({ ...ANSWER, state: "unsure" }));
    expect(refused.status === "error" && refused.problem?.title).toBe("Gone");
    vi.stubGlobal(
      "fetch",
      profile({ ontology: problemResponse(503, { title: "No ontology" }) }).fetchImpl,
    );
    const noOntology = await saveAttribute(IDLE, form({ ...ANSWER, state: "unsure" }));
    expect(noOntology.status === "error" && noOntology.problem?.title).toBe("No ontology");
  });
});

describe("addLocation", () => {
  const LOCATION_FORM = {
    business_id: ENTITY_ID,
    registration_id: REGISTRATION_ID,
    label: "EX-01",
    name: "Example location",
  };

  it("adds the location under the business's registration with links to its pages", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await addLocation({ status: "idle" }, form(LOCATION_FORM));
    expect(state).toEqual({
      status: "ok",
      value: {
        id: LOCATION_ID,
        label: "EX-01",
        name: "Example location",
        created: true,
        attributesHref: `/b/${ENTITY_ID}/attributes?node=${LOCATION_ID}`,
        snapshotHref: `/b/${ENTITY_ID}/snapshot?node=${LOCATION_ID}`,
      },
    });
    expect(fake.requests.find((request) => request.method === "POST")?.body).toEqual({
      registration_id: REGISTRATION_ID,
      label: "EX-01",
      name: "Example location",
    });
  });

  it("refuses a malformed form, a reader and a registration of another business", async () => {
    await signedInAs();
    const fake = profile();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const fields = await addLocation({ status: "idle" }, form({ ...LOCATION_FORM, label: "" }));
    expect(fields.status === "error" && fields.fieldErrors?.label).toEqual(["Enter a label."]);
    const tampered = await addLocation(
      { status: "idle" },
      form({ ...LOCATION_FORM, business_id: "x" }),
    );
    expect(tampered.status === "error" && tampered.formErrors?.[0]).toMatch(/Reload the page/);
    const foreign = await addLocation(
      { status: "idle" },
      form({ ...LOCATION_FORM, registration_id: USER_ID }),
    );
    expect(foreign.status === "error" && foreign.formErrors?.[0]).toMatch(
      /not part of the business/,
    );
    await signedInAs({ roles: ["compliance_lead"] });
    const reader = await addLocation({ status: "idle" }, form(LOCATION_FORM));
    expect(reader.status === "error" && reader.formErrors?.[0]).toMatch(/not change it/);
    expect(fake.requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("passes on a failed read of the business or a refused location", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      profile({ business: problemResponse(404, { title: "No business" }) }).fetchImpl,
    );
    const missing = await addLocation({ status: "idle" }, form(LOCATION_FORM));
    expect(missing.status === "error" && missing.problem?.title).toBe("No business");
    vi.stubGlobal(
      "fetch",
      profile({ location: problemResponse(422, { title: "Hierarchy invalid" }) }).fetchImpl,
    );
    const refused = await addLocation({ status: "idle" }, form(LOCATION_FORM));
    expect(refused.status === "error" && refused.problem?.title).toBe("Hierarchy invalid");
  });
});
