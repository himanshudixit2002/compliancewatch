// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { encodeFakeRefreshToken } from "@/server/auth/fake";
import { encryptPending } from "@/server/auth/pending";
import { resetEnvCache } from "@/server/env";
import { decryptSession, encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeIdentity, type IdentityFixture } from "@/test/identity-fixture";
import { enrolAuthenticator, removeAuthenticator, verifySecondFactor } from "./mfa-actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const IDLE = { status: "idle" } as const;
const PHONE = "+919876543210";

let identity: IdentityFixture;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  identity = fakeIdentity();
  vi.stubGlobal("fetch", identity.fetchImpl);
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  resetEnvCache();
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
});

describe("verifySecondFactor with the fake adapter", () => {
  it("completes a pending sign-in whose roles need the factor and returns to next", async () => {
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "ca_firm",
      roles: ["ca_admin"],
    });
    fakeCookies.set(
      "cw_pending",
      await encryptPending(
        {
          provider: "fake",
          session: {
            accessToken: identity.providerToken({ phone: PHONE }),
            refreshToken: encodeFakeRefreshToken({ phone: PHONE }, "aal1"),
            expiresAt: 0,
            aal: "aal1",
            subject: "s",
          },
          contact: { phone: PHONE },
          next: "/settings/team",
        },
        KEY,
      ),
    );
    await expect(verifySecondFactor(IDLE, form({}))).rejects.toMatchObject({
      href: "/settings/team",
    });
    const cookie = fakeCookies.written("cw_session");
    const claims = await decryptSession(cookie?.value as string, KEY);
    expect(claims).toMatchObject({ userId: user.id, mfa: true, roles: ["ca_admin"] });
    expect(fakeCookies.written("cw_pending")?.options.maxAge).toBe(0);
  });

  it("finishes the sign-up the pending cookie kept once the factor is confirmed", async () => {
    fakeCookies.set(
      "cw_pending",
      await encryptPending(
        {
          provider: "fake",
          session: {
            accessToken: identity.providerToken({ phone: PHONE }),
            refreshToken: encodeFakeRefreshToken({ phone: PHONE }, "aal1"),
            expiresAt: 0,
            aal: "aal1",
            subject: "s",
          },
          contact: { phone: PHONE },
          signUp: { kind: "ca_firm", name: "Example CA", displayName: "Example admin" },
        },
        KEY,
      ),
    );
    await expect(verifySecondFactor(IDLE, form({}))).rejects.toMatchObject({ href: "/onboarding" });
    const claims = await decryptSession(fakeCookies.written("cw_session")?.value as string, KEY);
    expect(claims).toMatchObject({
      tenantKind: "ca_firm",
      roles: ["ca_admin"],
      mfa: true,
      displayName: "Example admin",
    });
    expect([...identity.tenants.values()][0]?.name).toBe("Example CA");
  });

  it("re-exchanges a signed-in person's session so it carries the factor", async () => {
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const claims: SessionClaims = {
      userId: user.id,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      sv: 0,
      provider: "fake",
      ...sessionWindow(new Date(), 3600),
      cwToken: identity.accessToken(user),
      providerRefreshToken: encodeFakeRefreshToken({ phone: PHONE }, "aal1"),
    };
    fakeCookies.set("cw_session", await encryptSession(claims, KEY));
    await expect(verifySecondFactor(IDLE, form({ next: "/account" }))).rejects.toMatchObject({
      href: "/account",
    });
    const fresh = await decryptSession(fakeCookies.written("cw_session")?.value as string, KEY);
    expect(fresh?.mfa).toBe(true);
    await expect(verifySecondFactor(IDLE, form({}))).rejects.toMatchObject({
      href: "/account",
    });
  });

  it("says when nobody is here, and that the fake has nothing to enrol or remove", async () => {
    const nobody = await verifySecondFactor(IDLE, form({}));
    expect(nobody.status).toBe("error");
    if (nobody.status === "error") expect(nobody.problem?.type).toContain("web-mfa-no-session");
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    fakeCookies.set(
      "cw_session",
      await encryptSession(
        {
          userId: user.id,
          tenantId: user.tenantId,
          tenantKind: "business",
          roles: ["owner"],
          displayName: "x",
          mfa: false,
          sv: 0,
          provider: "fake",
          ...sessionWindow(new Date(), 3600),
          providerRefreshToken: encodeFakeRefreshToken({ phone: PHONE }, "aal1"),
        },
        KEY,
      ),
    );
    const enrol = await enrolAuthenticator(IDLE, form({}));
    expect(enrol.status).toBe("error");
    if (enrol.status === "error") expect(enrol.problem?.type).toContain("web-provider-unsupported");
    expect(await removeAuthenticator(IDLE, form({ code: "123456" }))).toEqual({
      status: "error",
      formErrors: ["No authenticator app is set up for this account yet."],
    });
  });
});
