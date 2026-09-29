// @vitest-environment node
import { randomBytes } from "node:crypto";
import { EncryptJWT } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { epochSeconds, sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { fakeCookies } from "@/test/fake-cookies";
import { EnvError, loadEnv, resetEnvCache } from "./env";
import {
  claimsFromPayload,
  clearSessionCookie,
  decryptSession,
  encryptSession,
  readSessionCookie,
  sessionCookieOptions,
  setSessionCookie,
} from "./session";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const OTHER_KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const NOW = new Date("2026-09-29T10:00:00Z");

const claims: SessionClaims = {
  userId: "00000000-0000-4000-8000-000000000001",
  tenantId: "00000000-0000-4000-8000-000000000002",
  tenantKind: "internal",
  roles: ["analyst", "reviewer"],
  displayName: "Example analyst",
  mfa: true,
  sv: 1,
  provider: "fake",
  ...sessionWindow(NOW, 28_800),
};

beforeEach(() => {
  fakeCookies.reset();
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("encryptSession and decryptSession", () => {
  it("round-trip the claims through a compact JWE and keep optional fields absent", async () => {
    const token = await encryptSession(claims, KEY);
    expect(token.split(".")).toHaveLength(5);
    expect(token).not.toContain("Example analyst");
    const back = await decryptSession(token, KEY, NOW);
    expect(back).toEqual(claims);
    expect(back).not.toHaveProperty("cwToken");
    expect(back).not.toHaveProperty("checkedAt");
  });

  it("carry the token fields when present", async () => {
    const withToken: SessionClaims = {
      ...claims,
      cwToken: "a-service-token",
      cwTokenExpiresAt: claims.issuedAt + 600,
      checkedAt: claims.issuedAt,
      analyticsConsent: false,
    };
    const back = await decryptSession(await encryptSession(withToken, KEY), KEY, NOW);
    expect(back).toEqual(withToken);
  });

  it("answer null for a tampered, truncated, foreign or expired token", async () => {
    const token = await encryptSession(claims, KEY);
    const [header, encryptedKey, iv, ciphertext, tag] = token.split(".") as [
      string,
      string,
      string,
      string,
      string,
    ];
    const flipped = `${ciphertext.slice(0, -2)}${ciphertext.endsWith("AA") ? "BB" : "AA"}`;
    expect(
      await decryptSession([header, encryptedKey, iv, flipped, tag].join("."), KEY),
    ).toBeNull();
    expect(await decryptSession(token.slice(0, -10), KEY)).toBeNull();
    expect(await decryptSession("not-a-token", KEY)).toBeNull();
    expect(await decryptSession("", KEY)).toBeNull();
    expect(await decryptSession(token, OTHER_KEY, NOW)).toBeNull();
    const afterExpiry = new Date((claims.expiresAt + 1) * 1000);
    expect(await decryptSession(token, KEY, afterExpiry)).toBeNull();
    const justBefore = new Date((claims.expiresAt - 1) * 1000);
    expect(await decryptSession(token, KEY, justBefore)).toEqual(claims);
  });

  it("reject a well-encrypted payload that is not a session", async () => {
    const iat = epochSeconds(NOW);
    const foreign = await new EncryptJWT({ userId: "u", roles: ["monarch"] })
      .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
      .setIssuedAt(iat)
      .setExpirationTime(iat + 60)
      .encrypt(KEY);
    expect(await decryptSession(foreign, KEY, NOW)).toBeNull();
    const signedOnly = await new EncryptJWT({ ...claims })
      .setProtectedHeader({ alg: "dir", enc: "A128CBC-HS256" })
      .encrypt(new Uint8Array(randomBytes(32)));
    expect(await decryptSession(signedOnly, KEY, NOW)).toBeNull();
  });

  it("use the environment's secret by default and refuse to run without one", async () => {
    vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
    const token = await encryptSession(claims);
    expect(await decryptSession(token, undefined, NOW)).toEqual(claims);
    vi.unstubAllEnvs();
    resetEnvCache();
    await expect(encryptSession(claims)).rejects.toThrow(EnvError);
    await expect(decryptSession(token)).rejects.toThrow(/CW_WEB_SESSION_SECRET is required/);
  });
});

describe("claimsFromPayload", () => {
  it("maps iat and exp and refuses unknown roles, kinds and providers", () => {
    const base = {
      userId: "u",
      tenantId: "t",
      tenantKind: "business",
      roles: ["owner"],
      displayName: "n",
      mfa: false,
      sv: 0,
      provider: "fake",
      iat: 1,
      exp: 2,
    };
    expect(claimsFromPayload(base)).toMatchObject({ issuedAt: 1, expiresAt: 2, roles: ["owner"] });
    expect(claimsFromPayload({ ...base, roles: [] })).toBeNull();
    expect(claimsFromPayload({ ...base, roles: ["monarch"] })).toBeNull();
    expect(claimsFromPayload({ ...base, tenantKind: "club" })).toBeNull();
    expect(claimsFromPayload({ ...base, provider: "keycloak" })).toBeNull();
    expect(claimsFromPayload({ ...base, sv: -1 })).toBeNull();
    expect(claimsFromPayload({ ...base, exp: "soon" })).toBeNull();
    expect(claimsFromPayload(null)).toBeNull();
    expect(claimsFromPayload("text")).toBeNull();
  });
});

describe("the cookie", () => {
  it("is httpOnly, lax, scoped to / and secure outside local, with the lifetime as max-age", () => {
    expect(sessionCookieOptions(loadEnv({}))).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: false,
      path: "/",
      maxAge: 28_800,
    });
    for (const name of ["test", "staging", "prod"]) {
      expect(sessionCookieOptions(loadEnv({ CW_WEB_ENV: name })).secure, name).toBe(true);
    }
    expect(sessionCookieOptions(loadEnv({ CW_WEB_SESSION_TTL_SECONDS: "600" })).maxAge).toBe(600);
  });

  it("is written with those options, read back, and expired on clear", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
    expect(await readSessionCookie()).toBeUndefined();
    await setSessionCookie(claims);
    const written = fakeCookies.written("cw_session");
    expect(written?.options).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/",
      maxAge: 28_800,
    });
    const value = await readSessionCookie();
    expect(value).toBe(written?.value);
    expect(await decryptSession(value as string, KEY, NOW)).toEqual(claims);
    await clearSessionCookie();
    const cleared = fakeCookies.written("cw_session");
    expect(cleared?.value).toBe("");
    expect(cleared?.options).toMatchObject({ maxAge: 0, httpOnly: true, path: "/" });
    expect(await readSessionCookie()).toBeUndefined();
  });
});
