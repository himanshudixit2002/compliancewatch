// @vitest-environment node
import { randomBytes } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { readRememberedRecipients, rememberRecipient } from "@/server/remembered-recipients";
import { encryptSession } from "@/server/session";
import { OWNER_ID, grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse, type RecordedRequest } from "@/test/fake-fetch";
import { TEMPLATE_DTOS, WHATSAPP_KEY, preferenceDto } from "@/test/notification-fixture";
import { chooseRecipient, forgetRecipient, savePreference } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const IDLE = { status: "idle" } as const;

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

const SAVE = {
  channel: "whatsapp",
  opted_in: "in",
  language: "hi",
  quiet_hours_start: "22:00",
  quiet_hours_end: "07:00",
};

/** Templates, consents and the preference routes as the services answer them. */
function services(
  options: { consentGiven?: boolean; failPut?: boolean; failTemplates?: boolean } = {},
) {
  return fakeFetch((request: RecordedRequest) => {
    if (request.pathname === "/v1/notification/templates") {
      return options.failTemplates === true
        ? problemResponse(503, { title: "Templates unavailable" })
        : jsonResponse(200, TEMPLATE_DTOS);
    }
    if (request.pathname === "/v1/identity/consents") {
      return jsonResponse(
        200,
        summaryDto(
          options.consentGiven === true
            ? [grantedState("whatsapp_reminders", "whatsapp-consent@0.0-example")]
            : [],
        ),
      );
    }
    if (request.method === "GET") return problemResponse(404, { type: "about:blank" });
    if (request.method === "PUT") {
      if (options.failPut === true) return problemResponse(422, { title: "Invalid preference" });
      const body = request.body as Record<string, unknown>;
      return jsonResponse(
        200,
        preferenceDto({
          opted_in: body.opted_in as boolean,
          language: body.language as string,
          quiet_hours_start: body.quiet_hours_start as string,
          quiet_hours_end: body.quiet_hours_end as string,
        }),
      );
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

describe("chooseRecipient", () => {
  it("remembers a checked number on this device and renders the page again", async () => {
    await signedInAs();
    const state = await chooseRecipient(
      IDLE,
      form({ channel: "whatsapp", recipient: "+91 00000 00000" }),
    );
    expect(state).toEqual({ status: "ok", value: undefined });
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({ whatsapp: WHATSAPP_KEY });
    expect(revalidatePath).toHaveBeenCalledWith("/settings/notifications");
  });

  it("puts what is wrong on the field, and refuses an unknown channel", async () => {
    await signedInAs();
    expect(await chooseRecipient(IDLE, form({ channel: "email", recipient: "owner" }))).toEqual({
      status: "error",
      fieldErrors: { recipient: ["Enter an email address, such as name@example.com."] },
    });
    expect(await chooseRecipient(IDLE, form({ channel: "fax", recipient: "x" }))).toEqual({
      status: "error",
      formErrors: ["Choose WhatsApp or email."],
    });
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({});
  });

  it("sends a visitor without a session to sign in", async () => {
    await expect(
      chooseRecipient(IDLE, form({ channel: "email", recipient: "owner@example.com" })),
    ).rejects.toMatchObject({ href: "/sign-in?next=%2Fsettings%2Fnotifications" });
  });
});

describe("forgetRecipient", () => {
  it("forgets the channel's recipient and ignores an unknown channel", async () => {
    await signedInAs();
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    await forgetRecipient(form({ channel: "fax" }));
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({ whatsapp: WHATSAPP_KEY });
    await forgetRecipient(form({ channel: "whatsapp" }));
    expect(await readRememberedRecipients(OWNER_ID)).toEqual({});
    expect(revalidatePath).toHaveBeenCalledWith("/settings/notifications");
  });
});

describe("savePreference", () => {
  it("replaces the remembered recipient's preference once the consent is on file", async () => {
    await signedInAs();
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    const fake = services({ consentGiven: true });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await savePreference(IDLE, form(SAVE));
    const put = fake.requests.find((request) => request.method === "PUT");
    expect(put?.pathname).toBe(`/v1/notification/preferences/whatsapp/${WHATSAPP_KEY}`);
    expect(put?.body).toEqual({
      opted_in: true,
      source: "web_settings",
      language: "hi",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
      subject: OWNER_ID,
    });
    expect(state).toEqual({
      status: "ok",
      value: undefined,
      message:
        "Saved for +910000000000 at 1 Jan 2000, 5:30 am IST: Opted in, quiet hours 22:00 to 07:00 IST, across midnight.",
    });
    expect(revalidatePath).toHaveBeenCalledWith("/settings/notifications");
  });

  it("refuses to opt in without the consent, and opts out without asking for it", async () => {
    await signedInAs();
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    const fake = services();
    vi.stubGlobal("fetch", fake.fetchImpl);
    const refused = await savePreference(IDLE, form(SAVE));
    expect(refused).toEqual({
      status: "error",
      formErrors: [
        "Your consent to WhatsApp reminders is not on file, so reminders were not switched on. Give it on the Consents page, or choose not to send reminders.",
      ],
      fieldErrors: {
        opted_in: ["Reminders can be switched on once your consent is on file."],
      },
    });
    expect(fake.requests.some((request) => request.method === "PUT")).toBe(false);
    const optedOut = await savePreference(IDLE, form({ ...SAVE, opted_in: "out" }));
    expect(optedOut.status === "ok" && optedOut.message).toContain("Opted out");
  });

  it("names the fields that are wrong before saving anything", async () => {
    await signedInAs();
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    const fake = services({ consentGiven: true });
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await savePreference(
      IDLE,
      form({ ...SAVE, language: "fr", quiet_hours_end: "7" }),
    );
    expect(state).toEqual({
      status: "error",
      fieldErrors: {
        language: ["Choose one of the languages listed."],
        quiet_hours_end: ["Enter a time as HH:MM on the 24-hour clock."],
      },
    });
    expect(fake.requests.some((request) => request.method === "PUT")).toBe(false);
  });

  it("needs a known channel and a recipient chosen on this device", async () => {
    await signedInAs();
    expect(await savePreference(IDLE, form({ ...SAVE, channel: "" }))).toEqual({
      status: "error",
      formErrors: ["Choose WhatsApp or email."],
    });
    expect(await savePreference(IDLE, form(SAVE))).toEqual({
      status: "error",
      formErrors: ["Name the WhatsApp recipient first."],
    });
  });

  it("reports the service's problem when a read or the save fails", async () => {
    await signedInAs();
    await rememberRecipient(OWNER_ID, "whatsapp", WHATSAPP_KEY);
    vi.stubGlobal("fetch", services({ failTemplates: true }).fetchImpl);
    const templates = await savePreference(IDLE, form(SAVE));
    expect(templates.status === "error" && templates.problem?.title).toBe("Templates unavailable");
    vi.stubGlobal("fetch", services({ consentGiven: true, failPut: true }).fetchImpl);
    const put = await savePreference(IDLE, form(SAVE));
    expect(put.status === "error" && put.problem?.title).toBe("Invalid preference");
    vi.stubGlobal(
      "fetch",
      fakeFetch((request) =>
        request.pathname === "/v1/identity/consents"
          ? problemResponse(503, { title: "Identity unavailable" })
          : request.pathname === "/v1/notification/templates"
            ? jsonResponse(200, TEMPLATE_DTOS)
            : problemResponse(404, { type: "about:blank" }),
      ).fetchImpl,
    );
    const consents = await savePreference(IDLE, form(SAVE));
    expect(consents.status === "error" && consents.problem?.title).toBe("Identity unavailable");
  });
});
