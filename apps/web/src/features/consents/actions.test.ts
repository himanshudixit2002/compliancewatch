// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { readLegalVersions } from "@/server/legal";
import { readRememberedRecipients, rememberRecipient } from "@/server/remembered-recipients";
import { encryptSession } from "@/server/session";
import { OWNER_ID, grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { changeConsent, recordConsents } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const IDLE = { status: "idle" } as const;
const NUMBER = "+919800000000";
const VERSIONS = readLegalVersions();
const TERMS = `terms-of-service@${VERSIONS["terms-of-service"].version}`;
const PRIVACY = `privacy-notice@${VERSIONS["privacy-notice"].version}`;
const WHATSAPP = `whatsapp-consent@${VERSIONS["whatsapp-consent"].version}`;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: OWNER_ID,
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

const REQUIRED = { terms: "on", privacy_notice: "on", profile_processing: "on" };

/** The identity and notification services: a summary, then each POST and PUT as recorded. */
function services(
  options: {
    states?: ReturnType<typeof grantedState>[];
    failPurpose?: string;
    failPut?: boolean;
  } = {},
) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.method === "GET" && request.pathname === "/v1/identity/consents") {
      return jsonResponse(200, summaryDto(options.states ?? []));
    }
    if (request.method === "POST" && request.pathname === "/v1/identity/consents") {
      const body = request.body as { purpose: string };
      if (body.purpose === options.failPurpose) {
        return problemResponse(503, { title: "Identity is unavailable" });
      }
      return jsonResponse(201, {
        id: "00000000-0000-4000-8000-000000000c01",
        recorded_at: "2000-01-01T00:00:00Z",
        ...(request.body as object),
      });
    }
    if (request.method === "PUT") {
      if (options.failPut === true) return problemResponse(422, { title: "Invalid recipient" });
      return jsonResponse(200, {
        channel: "whatsapp",
        recipient: NUMBER,
        opted_in: true,
        source: "web_onboarding",
        language: "en",
        quiet_hours_start: "21:00",
        quiet_hours_end: "08:00",
        updated_at: "2000-01-01T00:00:00Z",
      });
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

  function productEvents(log: { mock: { calls: unknown[][] } }): unknown[] {
    return log.mock.calls
      .map((call) => JSON.parse(String(call[0])) as { event?: string })
      .filter((line) => line.event === "product_event");
  }

  it("emits the consent step when the person also gave the analytics consent", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await signedInAs();
    vi.stubGlobal("fetch", services({ states: [grantedState("analytics", PRIVACY)] }).fetchImpl);
    await expect(recordConsents(IDLE, form(REQUIRED))).rejects.toThrow(Redirected);
    expect(productEvents(log)).toEqual([
      expect.objectContaining({
        name: "onboarding_step_completed",
        properties: { step: "consent" },
      }),
    ]);
  });

  it("emits nothing for a person who did not give the analytics consent", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await signedInAs();
    vi.stubGlobal("fetch", services().fetchImpl);
    await expect(recordConsents(IDLE, form(REQUIRED))).rejects.toThrow(Redirected);
    expect(productEvents(log)).toEqual([]);
  });

  /** Identity holding one analytics state that each recorded change replaces. */
  function analyticsState(granted: boolean) {
    let current = granted;
    return fakeFetch((request: RecordedRequest) => {
      if (request.method === "GET") {
        return jsonResponse(200, summaryDto([grantedState("analytics", PRIVACY, current)]));
      }
      const body = request.body as { granted: boolean };
      current = body.granted;
      return jsonResponse(201, {
        id: "00000000-0000-4000-8000-000000000c02",
        recorded_at: "2000-01-01T00:00:00Z",
        ...(request.body as object),
      });
    });
  }

  it("stops at a withdrawal of the analytics consent and starts again when it is given", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    await signedInAs();
    vi.stubGlobal("fetch", analyticsState(true).fetchImpl);
    const withdrawn = await changeConsent(IDLE, form({ purpose: "analytics", change: "withdraw" }));
    expect(withdrawn.status).toBe("ok");
    expect(productEvents(log)).toEqual([]);

    vi.stubGlobal("fetch", analyticsState(false).fetchImpl);
    const given = await changeConsent(IDLE, form({ purpose: "analytics", change: "give" }));
    expect(given.status).toBe("ok");
    expect(productEvents(log)).toEqual([
      expect.objectContaining({
        name: "consent_changed",
        properties: { purpose: "analytics", change: "give" },
      }),
    ]);
  });
});

describe("closed onboarding", () => {
  // In production every document in docs/legal is still a draft, so onboarding is closed.
  beforeEach(() => {
    vi.stubEnv("CW_WEB_ENV", "prod");
  });

  it("records no consent on the consent step", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await recordConsents(IDLE, form(REQUIRED));
    expect(state).toEqual({
      status: "error",
      formErrors: [
        "Onboarding is closed until the legal documents are reviewed; nothing was recorded.",
      ],
    });
    expect(fake.requests).toHaveLength(0);
  });

  it("refuses to give a consent on the settings page but still records a withdrawal", async () => {
    await signedInAs();
    const fake = services({ states: [grantedState("analytics", PRIVACY)] });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const given = await changeConsent(IDLE, form({ purpose: "email_reminders", change: "give" }));
    expect(given.status === "error" && given.formErrors?.[0]).toMatch(
      /^Consents cannot be given while the legal documents are drafts/,
    );
    expect(fake.requests).toHaveLength(0);

    const withdrawn = await changeConsent(IDLE, form({ purpose: "analytics", change: "withdraw" }));
    expect(withdrawn.status).toBe("ok");
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      "GET /v1/identity/consents",
      "POST /v1/identity/consents",
    ]);
  });
});

describe("recordConsents", () => {
  it("records each ticked purpose with its notice version and evidence, opts the number in and moves on", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const promise = recordConsents(
      IDLE,
      form({ ...REQUIRED, whatsapp_reminders: "on", analytics: "on", whatsapp_number: NUMBER }),
    );
    await expect(promise).rejects.toMatchObject({ href: "/onboarding/business" });
    const posts = fake.requests.filter((request) => request.method === "POST");
    expect(posts.map((request) => request.body)).toEqual([
      {
        subject: OWNER_ID,
        purpose: "terms",
        granted: true,
        source: "web_onboarding",
        notice_version: TERMS,
        evidence: "I accept the terms of service.",
        recorded_by: OWNER_ID,
      },
      expect.objectContaining({ purpose: "privacy_notice", notice_version: PRIVACY }),
      expect.objectContaining({ purpose: "profile_processing", notice_version: PRIVACY }),
      expect.objectContaining({
        purpose: "whatsapp_reminders",
        notice_version: WHATSAPP,
        evidence:
          "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time.",
      }),
      expect.objectContaining({ purpose: "analytics", notice_version: PRIVACY }),
    ]);
    for (const request of fake.requests) expect(request.headers["x-tenant-id"]).toBe(TENANT);
    const put = fake.requests.find((request) => request.method === "PUT");
    // Keyed as WhatsApp reports the number: the digits without the plus.
    expect(put?.pathname).toBe("/v1/notification/preferences/whatsapp/919800000000");
    expect(put?.body).toEqual({ opted_in: true, source: "web_onboarding" });
    expect(revalidatePath).toHaveBeenCalledWith("/onboarding");
    // The settings pages find the number again on this device.
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({ whatsapp: "919800000000" });
  });

  it("keeps an address the notifications page remembered when it remembers the number", async () => {
    // A browser sends a cookie only under its path, and the step posts to /onboarding.
    fakeCookies.visit("/settings/notifications");
    await rememberRecipient(OWNER_ID, "email", "owner@example.com");
    fakeCookies.visit("/onboarding");
    await signedInAs();
    vi.stubGlobal("fetch", services().fetchImpl);
    await expect(
      recordConsents(
        IDLE,
        form({ ...REQUIRED, whatsapp_reminders: "on", whatsapp_number: NUMBER }),
      ),
    ).rejects.toMatchObject({ href: "/onboarding/business" });
    fakeCookies.visit("/settings/notifications");
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({
      whatsapp: "919800000000",
      email: "owner@example.com",
    });
  });

  it("names the required boxes left unticked and records nothing", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await recordConsents(IDLE, form({ terms: "on" }));
    expect(state).toEqual({
      status: "error",
      fieldErrors: {
        privacy_notice: ["Tick this box to continue."],
        profile_processing: ["Tick this box to continue."],
      },
    });
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      "GET /v1/identity/consents",
    ]);
  });

  it("takes the required purposes already granted from the records, not from the form", async () => {
    await signedInAs();
    const fake = services({
      states: [
        grantedState("terms", "terms-of-service@0.0-example"),
        grantedState("privacy_notice", PRIVACY),
        grantedState("profile_processing", PRIVACY),
      ],
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(recordConsents(IDLE, form({ terms: "on" }))).rejects.toMatchObject({
      href: "/onboarding/business",
    });
    expect(
      fake.requests
        .filter((request) => request.method === "POST")
        .map((request) => (request.body as { purpose: string }).purpose),
    ).toEqual(["terms"]);
  });

  it("never withdraws an agreed purpose the form did not send, and leaves its number opted in", async () => {
    // WhatsApp reminders and analytics are granted at their current versions, so the step shows
    // them as agreed, with no box; the terms moved to a new version and are asked again.
    await signedInAs();
    const fake = services({
      states: [
        grantedState("terms", "terms-of-service@0.0-example"),
        grantedState("privacy_notice", PRIVACY),
        grantedState("profile_processing", PRIVACY),
        grantedState("whatsapp_reminders", WHATSAPP),
        grantedState("analytics", PRIVACY),
      ],
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(recordConsents(IDLE, form({ terms: "on" }))).rejects.toMatchObject({
      href: "/onboarding/business",
    });
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      "GET /v1/identity/consents",
      "POST /v1/identity/consents",
    ]);
    expect(fake.requests[1]?.body).toMatchObject({ purpose: "terms", granted: true });
  });

  it("records only what is missing at the current versions", async () => {
    await signedInAs();
    const fake = services({
      states: [grantedState("terms", TERMS), grantedState("privacy_notice", "privacy-notice@0.0")],
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(recordConsents(IDLE, form(REQUIRED))).rejects.toBeInstanceOf(Redirected);
    const purposes = fake.requests
      .filter((request) => request.method === "POST")
      .map((request) => (request.body as { purpose: string }).purpose);
    expect(purposes).toEqual(["privacy_notice", "profile_processing"]);
  });

  it("says what was recorded when a later record fails, with the problem", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ failPurpose: "profile_processing" }).fetchImpl);
    const state = await recordConsents(IDLE, form(REQUIRED));
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(state.problem?.title).toBe("Identity is unavailable");
    expect(state.problem?.correlationId).toMatch(/^[0-9a-f-]{36}$/);
    expect(state.formErrors).toEqual([
      "Recorded before the failure: Terms of service, Privacy notice. Agree again to record the rest; a purpose already recorded is not recorded twice.",
    ]);
  });

  it("says nothing was recorded when the first read or record fails", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ failPurpose: "terms" }).fetchImpl);
    const first = await recordConsents(IDLE, form(REQUIRED));
    expect(first.status === "error" && first.formErrors).toEqual([
      "Nothing was recorded before the failure.",
    ]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([{ path: "/v1/identity/consents", status: 401, problem: { title: "No tenant" } }])
        .fetchImpl,
    );
    const read = await recordConsents(IDLE, form(REQUIRED));
    expect(read.status === "error" && read.problem?.title).toBe("No tenant");
  });

  it("keeps the consents and says the number is not opted in when the preference fails", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ failPut: true }).fetchImpl);
    const state = await recordConsents(
      IDLE,
      form({ ...REQUIRED, whatsapp_reminders: "on", whatsapp_number: NUMBER }),
    );
    expect(state.status === "error" && state.problem?.title).toBe("Invalid recipient");
    expect(state.status === "error" && state.formErrors).toEqual([
      "Your consents are recorded, but the WhatsApp number is not opted in yet. Agree again to retry.",
    ]);
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({});
  });

  it("offers no WhatsApp opt-in to a CA firm", async () => {
    await signedInAs({ tenantKind: "ca_firm", roles: ["ca_admin"] });
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await recordConsents(
      IDLE,
      form({ ...REQUIRED, whatsapp_reminders: "on", whatsapp_number: NUMBER }),
    );
    expect(state.status === "error" && state.fieldErrors).toEqual({
      whatsapp_reminders: [
        "WhatsApp reminders are set for each client business, not for the firm.",
      ],
    });
    expect(fake.requests.map((request) => request.method)).toEqual(["GET"]);
  });

  it("sends a visitor without a session to sign in, and a role without the step to forbidden", async () => {
    await expect(recordConsents(IDLE, form(REQUIRED))).rejects.toMatchObject({
      href: "/sign-in?next=%2Fonboarding",
    });
    await signedInAs({ roles: ["compliance_lead"] });
    await expect(recordConsents(IDLE, form(REQUIRED))).rejects.toMatchObject({
      href: "/forbidden",
    });
  });
});

describe("changeConsent", () => {
  const WHATSAPP_GRANT = `whatsapp-consent@0.0-example`;

  it("opts the number out first, then records the withdrawal of the grant, and remembers the number", async () => {
    await signedInAs();
    const fake = services({ states: [grantedState("whatsapp_reminders", WHATSAPP_GRANT)] });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "withdraw", whatsapp_number: NUMBER }),
    );
    expect(fake.requests.map((request) => `${request.method} ${request.pathname}`)).toEqual([
      "GET /v1/identity/consents",
      "PUT /v1/notification/preferences/whatsapp/919800000000",
      "POST /v1/identity/consents",
    ]);
    expect(fake.requests[1]?.body).toEqual({ opted_in: false, source: "web_onboarding" });
    expect(fake.requests[2]?.body).toEqual({
      subject: OWNER_ID,
      purpose: "whatsapp_reminders",
      granted: false,
      source: "web_onboarding",
      notice_version: WHATSAPP_GRANT,
      evidence: "Confirmed on the settings page: Withdraw consent: WhatsApp reminders.",
      recorded_by: OWNER_ID,
    });
    expect(state).toEqual({
      status: "ok",
      value: {
        purpose: "whatsapp_reminders",
        change: "withdraw",
        recorded: true,
        number: NUMBER,
      },
      message: `Withdrawn: WhatsApp reminders, recorded 1 Jan 2000, 5:30 am IST. ${NUMBER} is opted out.`,
    });
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({ whatsapp: "919800000000" });
    expect(revalidatePath).toHaveBeenCalledWith("/settings/consents");
    expect(revalidatePath).toHaveBeenCalledWith("/settings/notifications");
  });

  it("records a withdrawal without a number and says no number was opted out", async () => {
    await signedInAs();
    const fake = services({ states: [grantedState("whatsapp_reminders", WHATSAPP_GRANT)] });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "withdraw", whatsapp_number: "" }),
    );
    expect(fake.requests.some((request) => request.method === "PUT")).toBe(false);
    expect(state.status === "ok" && state.message).toBe(
      "Withdrawn: WhatsApp reminders, recorded 1 Jan 2000, 5:30 am IST. No number was opted out.",
    );
  });

  it("gives email reminders at the current version with the checkbox sentence", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeConsent(IDLE, form({ purpose: "email_reminders", change: "give" }));
    const post = fake.requests.find((request) => request.method === "POST");
    expect(post?.body).toMatchObject({
      purpose: "email_reminders",
      granted: true,
      notice_version: PRIVACY,
      evidence: "Confirmed on the settings page: Send me reminders for this business by email.",
    });
    expect(state.status === "ok" && state.message).toBe(
      "Given: Email reminders, recorded 1 Jan 2000, 5:30 am IST.",
    );
  });

  it("gives WhatsApp reminders, then opts the number in", async () => {
    await signedInAs();
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "give", whatsapp_number: NUMBER }),
    );
    expect(fake.requests.map((request) => request.method)).toEqual(["GET", "POST", "PUT"]);
    expect(fake.requests[1]?.body).toMatchObject({ granted: true, notice_version: WHATSAPP });
    expect(fake.requests[2]?.body).toEqual({ opted_in: true, source: "web_onboarding" });
    expect(state.status === "ok" && state.message).toBe(
      `Given: WhatsApp reminders, recorded 1 Jan 2000, 5:30 am IST. ${NUMBER} is opted in.`,
    );
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({ whatsapp: "919800000000" });
  });

  it("records nothing for a change that is already the state", async () => {
    await signedInAs();
    const fake = services({ states: [grantedState("analytics", PRIVACY)] });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const given = await changeConsent(IDLE, form({ purpose: "analytics", change: "give" }));
    expect(given.status === "ok" && given.message).toBe(
      "Product analytics was already given for the current version, so nothing new was recorded.",
    );
    const withdrawn = await changeConsent(
      IDLE,
      form({ purpose: "email_reminders", change: "withdraw" }),
    );
    expect(withdrawn).toMatchObject({
      status: "ok",
      value: { recorded: false },
      message: "Email reminders was not given, so nothing new was recorded.",
    });
    expect(fake.requests.every((request) => request.method === "GET")).toBe(true);
  });

  it("records nothing when the number cannot be opted out", async () => {
    await signedInAs();
    const fake = services({
      states: [grantedState("whatsapp_reminders", WHATSAPP_GRANT)],
      failPut: true,
    });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "withdraw", whatsapp_number: NUMBER }),
    );
    expect(state.status === "error" && state.problem?.title).toBe("Invalid recipient");
    expect(state.status === "error" && state.formErrors).toEqual([
      "Nothing was recorded: the number could not be opted out.",
    ]);
    expect(fake.requests.some((request) => request.method === "POST")).toBe(false);
  });

  it("says the number is opted out when the withdrawal record then fails", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      services({
        states: [grantedState("whatsapp_reminders", WHATSAPP_GRANT)],
        failPurpose: "whatsapp_reminders",
      }).fetchImpl,
    );
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "withdraw", whatsapp_number: NUMBER }),
    );
    expect(state.status === "error" && state.formErrors).toEqual([
      "The number is opted out, but the withdrawal is not recorded yet. Try again.",
    ]);
  });

  it("says the consent is recorded when the opt-in then fails", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ failPut: true }).fetchImpl);
    const state = await changeConsent(
      IDLE,
      form({ purpose: "whatsapp_reminders", change: "give", whatsapp_number: NUMBER }),
    );
    expect(state.status === "error" && state.formErrors).toEqual([
      "Your consent is recorded, but the number is not opted in yet. Try again.",
    ]);
  });

  it("reports a failed record or read as nothing changed", async () => {
    await signedInAs();
    vi.stubGlobal("fetch", services({ failPurpose: "analytics" }).fetchImpl);
    const record = await changeConsent(IDLE, form({ purpose: "analytics", change: "give" }));
    expect(record.status === "error" && record.formErrors).toEqual(["Nothing was changed"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([{ path: "/v1/identity/consents", status: 503, problem: { title: "Down" } }])
        .fetchImpl,
    );
    const read = await changeConsent(IDLE, form({ purpose: "analytics", change: "give" }));
    expect(read.status === "error" && read.problem?.title).toBe("Down");
  });

  it("refuses a malformed change before calling anything", async () => {
    await signedInAs({ roles: ["compliance_lead"] });
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await changeConsent(IDLE, form({ purpose: "terms", change: "withdraw" }))).toEqual({
      status: "error",
      formErrors: ["This consent is not changed on this page."],
    });
    expect(
      await changeConsent(IDLE, form({ purpose: "whatsapp_reminders", change: "give" })),
    ).toEqual({
      status: "error",
      fieldErrors: { whatsapp_number: ["Enter the WhatsApp number the reminders go to."] },
    });
    expect(fake.requests).toEqual([]);
  });

  it("sends a visitor without a session to sign in", async () => {
    await expect(
      changeConsent(IDLE, form({ purpose: "analytics", change: "give" })),
    ).rejects.toMatchObject({ href: "/sign-in?next=%2Fsettings%2Fconsents" });
  });
});
