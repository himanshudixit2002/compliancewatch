// @vitest-environment node
import { randomBytes } from "node:crypto";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptPending } from "@/server/auth/pending";
import { resetEnvCache } from "@/server/env";
import { decryptSession } from "@/server/session";
import { fakeIdentity, type IdentityFixture } from "@/test/identity-fixture";
import { GET } from "./route";

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const EMAIL = "owner@example.test";

let identity: IdentityFixture;

function cookieOf(response: Response, name: string): string | undefined {
  const header = response.headers.getSetCookie().find((cookie) => cookie.startsWith(`${name}=`));
  return header?.split(";")[0]?.slice(name.length + 1);
}

function callback(
  query: Record<string, string>,
  headers: Record<string, string> = {},
): Promise<Response> {
  // The bind address, as `next start` builds request.nextUrl whatever host the browser used.
  const url = new URL("http://localhost:3000/auth/callback");
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
  return GET(new NextRequest(url, { headers }));
}

beforeEach(() => {
  identity = fakeIdentity();
  vi.stubGlobal("fetch", identity.fetchImpl);
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  resetEnvCache();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("GET /auth/callback", () => {
  it("signs a known person in from the link and returns to next", async () => {
    const user = identity.provision({
      contact: { email: EMAIL },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    const response = await callback({
      token_hash: identity.providerToken({ email: EMAIL }),
      type: "email",
      next: "/settings/team",
    });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/settings/team");
    const session = cookieOf(response, "cw_session");
    expect(session).toBeDefined();
    const claims = await decryptSession(session as string, KEY);
    expect(claims).toMatchObject({ userId: user.id, roles: ["owner"], provider: "fake" });
    expect(cookieOf(response, "cw_pending")).toBe("");
  });

  it("sends an unknown person to sign up with the pending cookie, never with a token in the URL", async () => {
    const response = await callback({
      token_hash: identity.providerToken({ email: EMAIL }),
      type: "email",
    });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/sign-up");
    const pending = await decryptPending(cookieOf(response, "cw_pending") as string, KEY);
    expect(pending?.contact).toEqual({ email: EMAIL });
    expect(pending?.provider).toBe("fake");
    expect(cookieOf(response, "cw_session")).toBeUndefined();
  });

  it("sends a role that needs a second factor to verify it first", async () => {
    identity.provision({ contact: { email: EMAIL }, kind: "ca_firm", roles: ["ca_admin"] });
    const response = await callback({
      token_hash: identity.providerToken({ email: EMAIL }),
      type: "email",
      next: "/settings/team",
    });
    expect(response.headers.get("location")).toBe("/account/mfa?next=%2Fsettings%2Fteam");
    expect(cookieOf(response, "cw_pending")).toBeDefined();
  });

  it("returns an invalid or missing link to the sign-in page", async () => {
    const missing = await callback({});
    expect(missing.headers.get("location")).toBe("/sign-in?error=link-expired");
    const broken = await callback({ token_hash: "not-a-token", next: "/account" });
    expect(broken.headers.get("location")).toBe("/sign-in?error=link-expired&next=%2Faccount");
    expect(broken.headers.getSetCookie()).toEqual([]);
  });

  it("names a refusal on the sign-in page", async () => {
    const user = identity.provision({
      contact: { email: EMAIL },
      kind: "business",
      roles: ["owner"],
    });
    identity.bump(user.id, { disabled: true });
    const response = await callback({ token_hash: identity.providerToken({ email: EMAIL }) });
    expect(response.headers.get("location")).toBe("/sign-in?error=disabled");
  });

  it("ignores a next that is not a same-origin path", async () => {
    identity.provision({ contact: { email: EMAIL }, kind: "business", roles: ["owner"] });
    const response = await callback({
      token_hash: identity.providerToken({ email: EMAIL }),
      next: "https://evil.example/",
    });
    expect(response.headers.get("location")).toBe("/businesses");
  });

  it("answers a relative Location, so a person on another host name stays there", async () => {
    identity.provision({ contact: { email: EMAIL }, kind: "business", roles: ["owner"] });
    const response = await callback(
      { token_hash: identity.providerToken({ email: EMAIL }), next: "/account" },
      { host: "app.example.com", "x-forwarded-host": "app.example.com" },
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/account");
    expect(cookieOf(response, "cw_session")).toBeDefined();
  });
});
