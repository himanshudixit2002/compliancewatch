// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptSession } from "@/server/session";
import { resetEnvCache } from "@/server/env";
import { fakeCookies } from "@/test/fake-cookies";
import { signIn } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const IDLE = { status: "idle" } as const;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

function form(entries: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
});

describe("signIn", () => {
  it("sets the cookie and redirects to the role's home", async () => {
    const promise = signIn(
      IDLE,
      form({ tenantKind: "internal", roles: ["analyst"], displayName: "Example analyst" }),
    );
    await expect(promise).rejects.toMatchObject({ href: "/admin" });
    const cookie = fakeCookies.written("cw_session");
    expect(cookie?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: "lax" });
    const claims = await decryptSession(cookie?.value as string, KEY);
    expect(claims).toMatchObject({
      tenantKind: "internal",
      roles: ["analyst"],
      displayName: "Example analyst",
      mfa: true,
      provider: "fake",
    });
    expect(claims && claims.expiresAt - claims.issuedAt).toBe(28_800);
  });

  it("honours a same-origin next and ignores a foreign one", async () => {
    const owner = { tenantKind: "business", roles: ["owner"], displayName: "Example owner" };
    await expect(signIn(IDLE, form({ ...owner, next: "/account" }))).rejects.toMatchObject({
      href: "/account",
    });
    await expect(
      signIn(IDLE, form({ ...owner, next: "https://evil.example/" })),
    ).rejects.toMatchObject({ href: "/businesses" });
    await expect(signIn(IDLE, form(owner))).rejects.toMatchObject({ href: "/businesses" });
  });

  it("returns field errors from the adapter without writing a cookie", async () => {
    const state = await signIn(
      IDLE,
      form({ tenantKind: "business", roles: ["analyst"], displayName: "" }),
    );
    expect(state).toEqual({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:web-fake-sign-in-invalid",
        title: "Check the sign-in details",
        correlationId: "",
      },
      fieldErrors: {
        displayName: ["Enter a display name."],
        roles: ["A business tenant cannot hold analyst; it allows owner, staff, compliance_lead."],
      },
    });
    expect(fakeCookies.written("cw_session")).toBeUndefined();
    expect(vi.mocked(redirect)).not.toHaveBeenCalled();
  });

  it("returns a shape error for a non-text field", async () => {
    const data = form({ tenantKind: "business", roles: ["owner"] });
    data.append("displayName", new Blob(["x"]), "name.txt");
    expect(await signIn(IDLE, data)).toEqual({
      status: "error",
      fieldErrors: { displayName: ["Expected a text value."] },
    });
  });

  it("reports an unconfigured provider as a problem naming the variable", async () => {
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "");
    resetEnvCache();
    const state = await signIn(
      IDLE,
      form({ tenantKind: "business", roles: ["owner"], displayName: "Example owner" }),
    );
    expect(state.status).toBe("error");
    if (state.status !== "error") return;
    expect(state.problem?.type).toBe("urn:compliancewatch:problem:web-auth-provider-missing");
    expect(state.problem?.detail).toContain("CW_WEB_AUTH_PROVIDER");
    expect(fakeCookies.written("cw_session")).toBeUndefined();
  });
});
