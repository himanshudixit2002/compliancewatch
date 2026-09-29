// @vitest-environment node
import { randomBytes } from "node:crypto";
import { EncryptJWT } from "jose";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeCookies } from "@/test/fake-cookies";
import { resetEnvCache } from "./env";
import {
  RECIPIENT_COOKIE_MAX_AGE_SECONDS,
  RECIPIENT_COOKIE_NAME,
  decryptRecipients,
  encryptRecipients,
  forgetRecipient,
  readRememberedRecipients,
  recipientCookieOptions,
  rememberRecipient,
} from "./remembered-recipients";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const USER = "00000000-0000-4000-8000-000000000001";
const OTHER_USER = "00000000-0000-4000-8000-000000000002";
const NUMBER = "919800000001";
const NOW = new Date("2000-01-01T00:00:00Z");

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  vi.stubEnv("CW_WEB_ENV", "test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("encryptRecipients and decryptRecipients", () => {
  it("round-trip the recipients of one user", async () => {
    const token = await encryptRecipients(USER, { whatsapp: NUMBER }, KEY, NOW);
    expect(token.split(".")).toHaveLength(5);
    expect(await decryptRecipients(token, USER, KEY, NOW)).toEqual({ whatsapp: NUMBER });
  });

  it("read as empty for another user, another key, an expired or a tampered value", async () => {
    const token = await encryptRecipients(USER, { email: "owner@example.com" }, KEY, NOW);
    expect(await decryptRecipients(token, OTHER_USER, KEY, NOW)).toEqual({});
    expect(await decryptRecipients(token, USER, new Uint8Array(randomBytes(32)), NOW)).toEqual({});
    const later = new Date(NOW.getTime() + (RECIPIENT_COOKIE_MAX_AGE_SECONDS + 60) * 1000);
    expect(await decryptRecipients(token, USER, KEY, later)).toEqual({});
    expect(await decryptRecipients(`${token.slice(0, -2)}xx`, USER, KEY, NOW)).toEqual({});
  });

  it("drops values that are not the service's keys and tokens of another kind", async () => {
    const wrongShape = await new EncryptJWT({
      kind: "cw-recipients",
      whatsapp: "+919800000001",
      email: "owner@example.com",
    })
      .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
      .setSubject(USER)
      .setExpirationTime("1h")
      .encrypt(KEY);
    expect(await decryptRecipients(wrongShape, USER, KEY)).toEqual({ email: "owner@example.com" });
    const session = await new EncryptJWT({ whatsapp: NUMBER })
      .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
      .setSubject(USER)
      .setExpirationTime("1h")
      .encrypt(KEY);
    expect(await decryptRecipients(session, USER, KEY)).toEqual({});
  });
});

describe("the recipient cookie", () => {
  it("is httpOnly, Lax, sent to the whole site for 30 days, and Secure outside local", () => {
    expect(recipientCookieOptions()).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/",
      maxAge: 30 * 24 * 60 * 60,
    });
    vi.stubEnv("CW_WEB_ENV", "local");
    resetEnvCache();
    expect(recipientCookieOptions().secure).toBe(false);
  });

  it("remembers a recipient per channel and keeps the others", async () => {
    expect(await readRememberedRecipients(USER)).toEqual({});
    await rememberRecipient(USER, "whatsapp", NUMBER);
    await rememberRecipient(USER, "email", "owner@example.com");
    expect(await readRememberedRecipients(USER)).toEqual({
      whatsapp: NUMBER,
      email: "owner@example.com",
    });
    expect(fakeCookies.written(RECIPIENT_COOKIE_NAME)?.options).toMatchObject({
      httpOnly: true,
      path: "/",
    });
    expect(await readRememberedRecipients(OTHER_USER)).toEqual({});
  });

  it("does not write again for the same value and refuses a value that is not a key", async () => {
    await rememberRecipient(USER, "whatsapp", NUMBER);
    const first = fakeCookies.written(RECIPIENT_COOKIE_NAME)?.value;
    await rememberRecipient(USER, "whatsapp", NUMBER);
    expect(fakeCookies.written(RECIPIENT_COOKIE_NAME)?.value).toBe(first);
    await expect(rememberRecipient(USER, "whatsapp", "+919800000001")).rejects.toThrow(
      "not a whatsapp recipient key",
    );
  });

  it("forgets one channel, and expires the cookie when nothing is left", async () => {
    await forgetRecipient(USER, "email");
    expect(fakeCookies.written(RECIPIENT_COOKIE_NAME)).toBeUndefined();
    await rememberRecipient(USER, "whatsapp", NUMBER);
    await rememberRecipient(USER, "email", "owner@example.com");
    await forgetRecipient(USER, "email");
    expect(await readRememberedRecipients(USER)).toEqual({ whatsapp: NUMBER });
    await forgetRecipient(USER, "whatsapp");
    const written = fakeCookies.written(RECIPIENT_COOKIE_NAME);
    expect(written?.value).toBe("");
    expect(written?.options).toMatchObject({ maxAge: 0, path: "/" });
    expect(await readRememberedRecipients(USER)).toEqual({});
  });
});
