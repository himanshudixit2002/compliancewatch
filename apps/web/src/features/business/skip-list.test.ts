// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { skipCookieName, skipKey } from "./model/questions";
import {
  SKIP_COOKIE_MAX_AGE_SECONDS,
  clearSkipList,
  readSkipList,
  rememberSkip,
} from "./skip-list";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const NAME = skipCookieName(ENTITY_ID);
const ITEM = skipKey(REGISTRATION_ID, "example_flag");

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.alloc(32, 7).toString("base64"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("the skip-list cookie", () => {
  it("is empty without a cookie", async () => {
    expect((await readSkipList(ENTITY_ID)).size).toBe(0);
  });

  it("remembers an unsure answer in an httpOnly cookie under /onboarding for a day", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    await rememberSkip(ENTITY_ID, ITEM, true);
    expect(await readSkipList(ENTITY_ID)).toEqual(new Set([ITEM]));
    expect(fakeCookies.written(NAME)?.options).toEqual({
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/onboarding",
      maxAge: SKIP_COOKIE_MAX_AGE_SECONDS,
    });
  });

  it("is not Secure on a local plain-HTTP server", async () => {
    vi.stubEnv("CW_WEB_ENV", "local");
    await rememberSkip(ENTITY_ID, ITEM, true);
    expect(fakeCookies.written(NAME)?.options.secure).toBe(false);
  });

  it("drops the item on another answer and writes nothing when nothing changes", async () => {
    await rememberSkip(ENTITY_ID, ITEM, false);
    expect(fakeCookies.written(NAME)).toBeUndefined();
    await rememberSkip(ENTITY_ID, ITEM, true);
    await rememberSkip(ENTITY_ID, ITEM, false);
    expect((await readSkipList(ENTITY_ID)).size).toBe(0);
  });

  it("forgets everything on request", async () => {
    await rememberSkip(ENTITY_ID, ITEM, true);
    await clearSkipList(ENTITY_ID);
    expect(fakeCookies.written(NAME)).toBeUndefined();
  });
});
