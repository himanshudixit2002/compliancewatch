// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { readLegalVersions } from "@/server/legal";
import { encryptSession } from "@/server/session";
import { OWNER_ID, grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { recordConsents } from "./actions";

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
  });

  it("names the required boxes left unticked and calls nothing", async () => {
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
    expect(fake.requests).toEqual([]);
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
    expect(fake.requests).toEqual([]);
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
