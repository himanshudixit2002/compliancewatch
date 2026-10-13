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
import { jsonResponse } from "@/test/fake-fetch";
import {
  GOTRUE_CHALLENGE,
  GOTRUE_ENROLMENT,
  GOTRUE_ERRORS,
  GOTRUE_USER,
  GOTRUE_USER_ID,
  gotrueAccessToken,
  gotrueSession,
} from "@/test/gotrue-fixtures";
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

/**
 * GoTrue as it spends refresh tokens: every refresh and every factor verify answers a new pair
 * and revokes the old one, and a refresh token used twice is refused. The identity stand-in
 * answers everything else; the web's fetch is routed by host.
 */
function gotrueStub(identity: IdentityFixture) {
  const spent = new Set<string>();
  const paths: string[] = [];
  let issued = 0;
  let current = "refresh-0";
  const rotate = (aal: "aal1" | "aal2") => {
    spent.add(current);
    issued += 1;
    current = `refresh-${issued}`;
    // The recorded expiry is a fixed instant; a live token lasts an hour from now.
    const expiresAt = Math.floor(Date.now() / 1000) + 3600;
    return { ...gotrueSession(aal), expires_at: expiresAt, refresh_token: current };
  };
  const fetchImpl = async (input: Request, init?: RequestInit): Promise<Response> => {
    const url = new URL(input.url);
    if (url.hostname !== "project.supabase.test") return identity.fetchImpl(input, init);
    paths.push(`${input.method} ${url.pathname}`);
    if (url.pathname === "/auth/v1/token") {
      const body = (await input.json()) as { refresh_token: string };
      if (spent.has(body.refresh_token) || body.refresh_token !== current) {
        return jsonResponse(400, GOTRUE_ERRORS.refreshRevoked);
      }
      return jsonResponse(200, rotate("aal1"));
    }
    if (url.pathname === "/auth/v1/user") return jsonResponse(200, GOTRUE_USER);
    if (url.pathname === "/auth/v1/factors") return jsonResponse(200, GOTRUE_ENROLMENT);
    if (url.pathname.endsWith("/challenge")) return jsonResponse(200, GOTRUE_CHALLENGE);
    if (url.pathname.endsWith("/verify")) return jsonResponse(200, rotate("aal2"));
    if (input.method === "DELETE") return jsonResponse(200, { id: "x" });
    return jsonResponse(404, {});
  };
  return { fetchImpl, paths, spent, refreshToken: () => current };
}

describe("the MFA actions with the supabase adapter", () => {
  const NOW = Math.floor(Date.now() / 1000);

  function useSupabase(identity: IdentityFixture) {
    const gotrue = gotrueStub(identity);
    vi.stubGlobal("fetch", gotrue.fetchImpl);
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "supabase");
    vi.stubEnv("CW_WEB_SUPABASE_URL", "https://project.supabase.test");
    vi.stubEnv("CW_WEB_SUPABASE_ANON_KEY", "anon-key-synthetic");
    resetEnvCache();
    return gotrue;
  }

  /** A business owner identity knows by GoTrue's subject, signed in without a second factor. */
  function ownerClaims(identity: IdentityFixture, provider: Partial<SessionClaims>): SessionClaims {
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    user.subject = GOTRUE_USER_ID;
    return {
      userId: user.id,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      sv: 0,
      provider: "supabase",
      ...sessionWindow(new Date(), 3600),
      cwToken: identity.accessToken(user),
      cwTokenExpiresAt: NOW + 600,
      providerAccessToken: gotrueAccessToken({ sub: GOTRUE_USER_ID, aal: "aal1" }),
      providerAccessExpiresAt: NOW + 3600,
      providerRefreshToken: "refresh-0",
      ...provider,
    };
  }

  async function sessionCookie(): Promise<SessionClaims | null> {
    const written = fakeCookies.written("cw_session");
    return written === undefined ? null : decryptSession(written.value, KEY);
  }

  it("acts with the cookie's provider token and writes the pair a verify rotates back", async () => {
    const gotrue = useSupabase(identity);
    const seeded = await encryptSession(ownerClaims(identity, {}), KEY);
    fakeCookies.set("cw_session", seeded);
    const enrolled = await enrolAuthenticator(IDLE, form({ friendlyName: "Work phone" }));
    expect(enrolled.status).toBe("ok");
    if (enrolled.status === "ok") {
      expect(enrolled.value?.enrolment?.factorId).toBe(GOTRUE_ENROLMENT.id);
    }
    // A current token is used as it is: no refresh, nothing to write back.
    expect(gotrue.paths).toEqual(["POST /auth/v1/factors"]);
    expect(fakeCookies.written("cw_session")?.value).toBe(seeded);
    await expect(
      verifySecondFactor(IDLE, form({ factorId: GOTRUE_ENROLMENT.id, code: "123456" })),
    ).rejects.toMatchObject({ href: "/account" });
    expect(gotrue.paths.slice(1)).toEqual([
      `POST /auth/v1/factors/${GOTRUE_ENROLMENT.id}/challenge`,
      `POST /auth/v1/factors/${GOTRUE_ENROLMENT.id}/verify`,
    ]);
    const after = await sessionCookie();
    expect(after).toMatchObject({ mfa: true, providerRefreshToken: "refresh-1" });
    expect(after?.providerAccessToken).toBe(gotrueSession("aal2").access_token);
    expect(gotrue.spent.has("refresh-0")).toBe(true);
  });

  it("refreshes a stale provider token once and writes it back before answering", async () => {
    const gotrue = useSupabase(identity);
    const stale = ownerClaims(identity, { providerAccessExpiresAt: NOW + 10 });
    fakeCookies.set("cw_session", await encryptSession(stale, KEY));
    const enrolled = await enrolAuthenticator(IDLE, form({}));
    expect(enrolled.status).toBe("ok");
    expect(gotrue.paths).toEqual(["POST /auth/v1/token", "POST /auth/v1/factors"]);
    const rotated = await sessionCookie();
    expect(rotated).toMatchObject({ providerRefreshToken: "refresh-1", cwToken: stale.cwToken });
    expect(rotated?.providerAccessExpiresAt).toBeGreaterThan(NOW + 3000);
    // The pair the cookie would have kept without that write is spent: GoTrue refuses it.
    fakeCookies.reset();
    fakeCookies.set("cw_session", await encryptSession(stale, KEY));
    const reused = await enrolAuthenticator(IDLE, form({}));
    expect(reused.status).toBe("error");
    if (reused.status === "error") expect(reused.problem?.type).toContain("web-provider-expired");
    // The written cookie carries on: its token is current, so no refresh is asked for.
    fakeCookies.reset();
    fakeCookies.set("cw_session", await encryptSession(rotated as SessionClaims, KEY));
    gotrue.paths.length = 0;
    expect((await enrolAuthenticator(IDLE, form({}))).status).toBe("ok");
    expect(gotrue.paths).toEqual(["POST /auth/v1/factors"]);
  });

  it("removes a factor with a fresh code and keeps the pair the verify rotated", async () => {
    const gotrue = useSupabase(identity);
    fakeCookies.set("cw_session", await encryptSession(ownerClaims(identity, {}), KEY));
    await expect(
      removeAuthenticator(
        IDLE,
        form({ factorId: GOTRUE_USER.factors[0]?.id ?? "", code: "123456" }),
      ),
    ).rejects.toMatchObject({ href: "/account/mfa" });
    expect(gotrue.paths.at(-1)).toBe(`DELETE /auth/v1/factors/${GOTRUE_USER.factors[0]?.id}`);
    expect(await sessionCookie()).toMatchObject({ providerRefreshToken: "refresh-1" });
  });

  it("lists a pending sign-in's factors from the user route and verifies the first verified one", async () => {
    const gotrue = useSupabase(identity);
    const admin = identity.provision({
      contact: { phone: PHONE },
      kind: "ca_firm",
      roles: ["ca_admin"],
    });
    admin.subject = GOTRUE_USER_ID;
    fakeCookies.set(
      "cw_pending",
      await encryptPending(
        {
          provider: "supabase",
          session: {
            accessToken: gotrueAccessToken({ sub: GOTRUE_USER_ID, aal: "aal1" }),
            refreshToken: "refresh-0",
            expiresAt: NOW + 3600,
            aal: "aal1",
            subject: GOTRUE_USER_ID,
          },
          contact: { phone: PHONE },
          next: "/settings/team",
        },
        KEY,
      ),
    );
    await expect(verifySecondFactor(IDLE, form({ code: "123456" }))).rejects.toMatchObject({
      href: "/settings/team",
    });
    const verified = GOTRUE_USER.factors[0]?.id;
    expect(gotrue.paths).toEqual([
      "GET /auth/v1/user",
      `POST /auth/v1/factors/${verified}/challenge`,
      `POST /auth/v1/factors/${verified}/verify`,
    ]);
    expect(await sessionCookie()).toMatchObject({
      userId: admin.id,
      mfa: true,
      providerRefreshToken: "refresh-1",
    });
  });
});
