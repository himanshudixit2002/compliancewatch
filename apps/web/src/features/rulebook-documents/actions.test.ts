// @vitest-environment node
import { randomBytes } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { documentDto } from "@/test/rulebook-fixture";
import { openDocument } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const ID = "51f5dbee-1615-f0ec-4725-6abddb11061a";

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

class NotFound extends Error {}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
    tenantId: "00000000-0000-4000-8000-00000000000a",
    tenantKind: "internal",
    roles: ["analyst"],
    displayName: "Example analyst",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(value: string): FormData {
  const data = new FormData();
  data.append("document_id", value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new NotFound();
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("openDocument", () => {
  it("opens the viewer for a document the rulebook holds, from its sha256", async () => {
    await signedInAs();
    const fake = fakeFetch((request) =>
      request.pathname === `/v1/rulebook/documents/${ID}`
        ? jsonResponse(200, documentDto({ document_id: ID }))
        : problemResponse(404),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    await expect(
      openDocument(IDLE, form("51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed")),
    ).rejects.toMatchObject({ href: `/admin/rulebook/documents/${ID}` });
  });

  it("answers on the field for an id the rulebook does not hold", async () => {
    await signedInAs();
    vi.stubGlobal(
      "fetch",
      fakeFetch(() =>
        problemResponse(404, {
          type: "urn:compliancewatch:problem:rulebook-document-not-found",
          title: "Document not found",
        }),
      ).fetchImpl,
    );
    expect(await openDocument(IDLE, form(ID))).toEqual({
      status: "error",
      fieldErrors: { document_id: ["The rulebook holds no document with this id."] },
    });
  });

  it("refuses a malformed id before any request, and passes another failure on", async () => {
    await signedInAs();
    const fake = fakeFetch(() => problemResponse(503, { title: "Rulebook unavailable" }));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const malformed = await openDocument(IDLE, form("nope"));
    expect(malformed.status === "error" && malformed.fieldErrors?.document_id).toEqual([
      "This is not a document id (32 hex characters) or a sha256 (64 hex characters).",
    ]);
    expect(fake.requests).toHaveLength(0);
    const failed = await openDocument(IDLE, form(ID));
    expect(failed.status === "error" && failed.problem?.title).toBe("Rulebook unavailable");
  });

  it("is a 404 for a tenant role and a sign-in for a visitor", async () => {
    await expect(openDocument(IDLE, form(ID))).rejects.toMatchObject({
      href: "/sign-in?next=%2Fadmin%2Frulebook%2Fdocuments",
    });
    await signedInAs({ tenantKind: "business", roles: ["owner"] });
    await expect(openDocument(IDLE, form(ID))).rejects.toBeInstanceOf(NotFound);
  });
});
