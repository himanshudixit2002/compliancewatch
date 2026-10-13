// @vitest-environment node
import { describe, expect, it } from "vitest";
import { fakeFetch, jsonResponse, type RecordedRequest } from "@/test/fake-fetch";
import {
  GOTRUE_CHALLENGE,
  GOTRUE_ENROLMENT,
  GOTRUE_ERRORS,
  GOTRUE_USER,
  GOTRUE_USER_ID,
  gotrueSession,
} from "@/test/gotrue-fixtures";
import { EnvError, loadEnv } from "../env";
import { providerFailureKind, type ProviderSession } from "./provider";
import { SupabaseAuthProvider, mapGotrueError, sessionFromGotrue } from "./supabase";

const URL_BASE = "https://project.supabase.test";
const ANON = "anon-key-synthetic";
const PHONE = "+919876543210";

const env = loadEnv({
  CW_WEB_ENV: "test",
  CW_WEB_AUTH_PROVIDER: "supabase",
  CW_WEB_SUPABASE_URL: `${URL_BASE}/`,
  CW_WEB_SUPABASE_ANON_KEY: ANON,
  CW_WEB_REQUEST_TIMEOUT_MS: "500",
});

function adapter(handler: Parameters<typeof fakeFetch>[0]) {
  const fake = fakeFetch(handler);
  return { fake, supabase: new SupabaseAuthProvider(env, { fetchImpl: fake.fetchImpl }) };
}

function session(aal: "aal1" | "aal2" = "aal1"): ProviderSession {
  return sessionFromGotrue(gotrueSession(aal)) as ProviderSession;
}

function expectCommonHeaders(request: RecordedRequest | undefined, token?: string) {
  expect(request?.headers.apikey).toBe(ANON);
  expect(request?.headers.accept).toBe("application/json");
  if (token === undefined) expect(request?.headers.authorization).toBeUndefined();
  else expect(request?.headers.authorization).toBe(`Bearer ${token}`);
}

describe("SupabaseAuthProvider", () => {
  it("needs the URL and the anon key", () => {
    expect(
      () => new SupabaseAuthProvider(loadEnv({ CW_WEB_ENV: "test", CW_WEB_AUTH_PROVIDER: "fake" })),
    ).toThrow(EnvError);
  });

  it("sends the OTP to a phone and verifies it into a session with the token's aal", async () => {
    const { fake, supabase } = adapter([
      { method: "POST", path: "/auth/v1/otp", body: {} },
      { method: "POST", path: "/auth/v1/verify", body: gotrueSession("aal1") },
    ]);
    expect((await supabase.startPhoneOtp(PHONE)).ok).toBe(true);
    const otp = fake.requests[0];
    expect(otp?.url).toBe(`${URL_BASE}/auth/v1/otp`);
    expect(otp?.body).toEqual({ phone: PHONE });
    expectCommonHeaders(otp);
    const verified = await supabase.verifyPhoneOtp(PHONE, " 123456 ");
    expect(verified.ok).toBe(true);
    if (!verified.ok) return;
    expect(fake.requests[1]?.body).toEqual({ type: "sms", phone: PHONE, token: "123456" });
    expect(verified.value).toMatchObject({
      refreshToken: "refresh-token-synthetic",
      expiresAt: 1_790_679_600,
      aal: "aal1",
      subject: GOTRUE_USER_ID,
    });
    expect((await supabase.startPhoneOtp("12345")).ok).toBe(false);
  });

  it("sends the email link with the callback and exchanges the hash", async () => {
    const { fake, supabase } = adapter([
      { method: "POST", path: "/auth/v1/otp", body: {} },
      { method: "POST", path: "/auth/v1/verify", body: gotrueSession("aal1") },
    ]);
    const sent = await supabase.sendEmailLink(
      "Owner@Example.test",
      "https://app.example/auth/callback",
    );
    expect(sent.ok).toBe(true);
    if (sent.ok) expect(sent.value.devLink).toBeUndefined();
    const otp = fake.requests[0];
    expect(otp?.body).toEqual({ email: "owner@example.test", create_user: true });
    expect(new URL(otp?.url as string).searchParams.get("redirect_to")).toBe(
      "https://app.example/auth/callback",
    );
    const exchanged = await supabase.exchangeEmailLink("hash-synthetic");
    expect(exchanged.ok).toBe(true);
    expect(fake.requests[1]?.body).toEqual({ type: "magiclink", token_hash: "hash-synthetic" });
  });

  it("refreshes through the token route and signs out with the fresh access token", async () => {
    const { fake, supabase } = adapter([
      { method: "POST", path: "/auth/v1/token", body: gotrueSession("aal2") },
      { method: "POST", path: "/auth/v1/logout", status: 204 },
    ]);
    const refreshed = await supabase.refresh("refresh-token-synthetic");
    expect(refreshed.ok).toBe(true);
    if (!refreshed.ok) return;
    expect(refreshed.value.aal).toBe("aal2");
    const token = fake.requests[0];
    expect(new URL(token?.url as string).searchParams.get("grant_type")).toBe("refresh_token");
    expect(token?.body).toEqual({ refresh_token: "refresh-token-synthetic" });
    await supabase.signOut("refresh-token-synthetic");
    const logout = fake.requests[2];
    expect(logout?.pathname).toBe("/auth/v1/logout");
    expectCommonHeaders(logout, refreshed.value.accessToken);
    expect(new URL(logout?.url as string).searchParams.get("scope")).toBe("local");
  });

  it("lists, enrols, challenges, verifies and removes TOTP factors with the person's token", async () => {
    const { fake, supabase } = adapter([
      { method: "GET", path: "/auth/v1/user", body: GOTRUE_USER },
      { method: "POST", path: "/auth/v1/factors", body: GOTRUE_ENROLMENT },
      { method: "POST", path: /\/auth\/v1\/factors\/[^/]+\/challenge$/, body: GOTRUE_CHALLENGE },
      { method: "POST", path: /\/auth\/v1\/factors\/[^/]+\/verify$/, body: gotrueSession("aal2") },
      { method: "DELETE", path: /\/auth\/v1\/factors\/[^/]+$/, status: 200, body: { id: "x" } },
    ]);
    const current = session();
    const factors = await supabase.mfa.listFactors(current);
    expect(factors.ok).toBe(true);
    if (factors.ok) {
      expect(factors.value).toEqual([
        {
          id: GOTRUE_USER.factors[0]?.id,
          type: "totp",
          status: "verified",
          friendlyName: "Work phone",
        },
        {
          id: GOTRUE_USER.factors[1]?.id,
          type: "totp",
          status: "unverified",
          friendlyName: "Old phone",
        },
      ]);
    }
    expect(fake.requests[0]?.method).toBe("GET");
    expect(fake.requests[0]?.pathname).toBe("/auth/v1/user");
    expectCommonHeaders(fake.requests[0], current.accessToken);
    const enrolled = await supabase.mfa.enrolTotp(current, "Work phone");
    expect(enrolled.ok).toBe(true);
    if (enrolled.ok) {
      expect(enrolled.value).toEqual({
        factorId: GOTRUE_ENROLMENT.id,
        qrSvg: GOTRUE_ENROLMENT.totp.qr_code,
        secret: "JBSWY3DPEHPK3PXP",
      });
    }
    expect(fake.requests[1]?.body).toEqual({
      factor_type: "totp",
      friendly_name: "Work phone",
      issuer: "ComplianceWatch",
    });
    const challenge = await supabase.mfa.challenge(current, GOTRUE_ENROLMENT.id);
    expect(challenge.ok && challenge.value).toEqual({
      challengeId: GOTRUE_CHALLENGE.id,
      expiresAt: 1_790_676_300,
    });
    expect(fake.requests[2]?.pathname).toBe(`/auth/v1/factors/${GOTRUE_ENROLMENT.id}/challenge`);
    const verified = await supabase.mfa.verify(
      current,
      GOTRUE_ENROLMENT.id,
      GOTRUE_CHALLENGE.id,
      "654321",
    );
    expect(verified.ok && verified.value.aal).toBe("aal2");
    expect(fake.requests[3]?.body).toEqual({ challenge_id: GOTRUE_CHALLENGE.id, code: "654321" });
    const removed = await supabase.mfa.remove(current, GOTRUE_ENROLMENT.id);
    expect(removed.ok).toBe(true);
    expect(fake.requests[4]?.method).toBe("DELETE");
  });

  it("maps GoTrue's refusals to the kinds the forms word", async () => {
    const { supabase } = adapter((request) => {
      if (request.pathname === "/auth/v1/otp") {
        return jsonResponse(429, GOTRUE_ERRORS.rateLimited, { "retry-after": "60" });
      }
      if (request.pathname === "/auth/v1/verify") {
        const body = request.body as { type: string };
        return body.type === "magiclink"
          ? jsonResponse(403, GOTRUE_ERRORS.invalidCode)
          : jsonResponse(422, GOTRUE_ERRORS.wrongCode);
      }
      if (request.pathname === "/auth/v1/token")
        return jsonResponse(400, GOTRUE_ERRORS.refreshRevoked);
      return jsonResponse(500, GOTRUE_ERRORS.unavailable);
    });
    const limited = await supabase.startPhoneOtp(PHONE);
    expect(limited.ok).toBe(false);
    if (!limited.ok) {
      expect(providerFailureKind(limited.error)).toBe("rate_limited");
      expect(limited.error.retryAfterSeconds).toBe(60);
      expect(limited.error.problem?.detail).toContain("60 seconds");
    }
    const wrong = await supabase.verifyPhoneOtp(PHONE, "000000");
    expect(wrong.ok).toBe(false);
    if (!wrong.ok) {
      expect(providerFailureKind(wrong.error)).toBe("invalid_code");
      expect(wrong.error.fieldErrors).toEqual({ code: ["Check the code."] });
    }
    const link = await supabase.exchangeEmailLink("stale");
    expect(link.ok).toBe(false);
    if (!link.ok) expect(providerFailureKind(link.error)).toBe("expired");
    const refresh = await supabase.refresh("used");
    expect(refresh.ok).toBe(false);
    if (!refresh.ok) expect(providerFailureKind(refresh.error)).toBe("expired");
    const factors = await supabase.mfa.listFactors(session());
    expect(factors.ok).toBe(false);
    if (!factors.ok) expect(providerFailureKind(factors.error)).toBe("unavailable");
  });

  it("reports a provider that does not answer as unavailable", async () => {
    const { supabase } = adapter(() => {
      throw new TypeError("fetch failed");
    });
    const result = await supabase.startPhoneOtp(PHONE);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(providerFailureKind(result.error)).toBe("unavailable");
      expect(result.error.problem?.detail).toContain("could not be reached");
    }
    await expect(supabase.signOut("x")).resolves.toBeUndefined();
  });
});

describe("sessionFromGotrue and mapGotrueError", () => {
  it("read the session's level from the token and refuse a body without tokens", () => {
    expect(sessionFromGotrue(gotrueSession("aal2"))?.aal).toBe("aal2");
    expect(sessionFromGotrue({ access_token: "x" })).toBeNull();
    expect(sessionFromGotrue(null)).toBeNull();
    const noExpiry = sessionFromGotrue(
      { access_token: "a.b.c", refresh_token: "r", expires_in: 100 },
      new Date(1_000_000 * 1000),
    );
    expect(noExpiry?.expiresAt).toBe(1_000_100);
    expect(noExpiry?.subject).toBe("");
  });

  it("maps by status and code", () => {
    expect(providerFailureKind(mapGotrueError(429, null, "otp", 30))).toBe("rate_limited");
    expect(providerFailureKind(mapGotrueError(503, null, "mfa"))).toBe("unavailable");
    expect(providerFailureKind(mapGotrueError(403, GOTRUE_ERRORS.invalidCode, "verify"))).toBe(
      "expired",
    );
    expect(providerFailureKind(mapGotrueError(400, GOTRUE_ERRORS.wrongCode, "verify"))).toBe(
      "invalid_code",
    );
    expect(providerFailureKind(mapGotrueError(401, null, "verify"))).toBe("expired");
    expect(providerFailureKind(mapGotrueError(401, null, "magiclink"))).toBe("invalid_link");
    expect(providerFailureKind(mapGotrueError(422, GOTRUE_ERRORS.badPhone, "otp"))).toBe(
      "invalid_contact",
    );
    expect(providerFailureKind(mapGotrueError(403, null, "logout"))).toBe("unavailable");
  });
});
