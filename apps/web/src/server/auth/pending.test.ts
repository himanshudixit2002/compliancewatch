// @vitest-environment node
import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeCookies } from "@/test/fake-cookies";
import { loadEnv, resetEnvCache } from "../env";
import {
  PENDING_COOKIE_NAME,
  PENDING_TTL_SECONDS,
  clearPendingCookie,
  decryptPending,
  encryptPending,
  pendingCookieOptions,
  readPending,
  setPendingCookie,
  type PendingSignIn,
} from "./pending";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const NOW = new Date("2026-09-29T10:00:00Z");

const pending: PendingSignIn = {
  provider: "fake",
  session: {
    accessToken: "provider-token",
    refreshToken: "fake.v1.x",
    expiresAt: 1_790_679_600,
    aal: "aal1",
    subject: "subject-1",
  },
  contact: { phone: "+919876543210" },
  next: "/settings/team",
};

beforeEach(() => {
  fakeCookies.reset();
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("encryptPending and decryptPending", () => {
  it("round-trip the pending sign-in, with or without a sign-up, for five minutes", async () => {
    const token = await encryptPending(pending, KEY, NOW);
    expect(token).not.toContain("provider-token");
    expect(await decryptPending(token, KEY, NOW)).toEqual(pending);
    const withSignUp: PendingSignIn = {
      ...pending,
      signUp: { kind: "ca_firm", name: "Example CA", displayName: "Example admin" },
    };
    expect(await decryptPending(await encryptPending(withSignUp, KEY, NOW), KEY, NOW)).toEqual(
      withSignUp,
    );
    const later = new Date(NOW.getTime() + (PENDING_TTL_SECONDS + 1) * 1000);
    expect(await decryptPending(token, KEY, later)).toBeNull();
    expect(await decryptPending(token, new Uint8Array(randomBytes(32)), NOW)).toBeNull();
    expect(await decryptPending("junk", KEY, NOW)).toBeNull();
  });

  it("keeps absent fields absent", async () => {
    const minimal: PendingSignIn = {
      provider: "supabase",
      session: pending.session,
      contact: { email: "a@example.test" },
    };
    const back = await decryptPending(await encryptPending(minimal, KEY, NOW), KEY, NOW);
    expect(back).toEqual(minimal);
    expect(back).not.toHaveProperty("next");
    expect(back?.contact).not.toHaveProperty("phone");
  });
});

describe("the cookie", () => {
  it("is httpOnly, lax, secure outside local, five minutes long, and read back", async () => {
    expect(pendingCookieOptions(loadEnv({ CW_WEB_ENV: "local" }))).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: false,
      path: "/",
      maxAge: PENDING_TTL_SECONDS,
    });
    expect(pendingCookieOptions(loadEnv({ CW_WEB_ENV: "prod" })).secure).toBe(true);
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
    expect(await readPending()).toBeNull();
    await setPendingCookie(pending);
    const written = fakeCookies.written(PENDING_COOKIE_NAME);
    expect(written?.options).toMatchObject({ httpOnly: true, secure: true, maxAge: 300 });
    expect(await readPending()).toEqual(pending);
    await clearPendingCookie();
    expect(fakeCookies.written(PENDING_COOKIE_NAME)?.options.maxAge).toBe(0);
    expect(await readPending()).toBeNull();
  });
});
