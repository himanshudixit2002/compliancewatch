// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decryptPending, encryptPending } from "@/server/auth/pending";
import { resetEnvCache } from "@/server/env";
import { decryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeIdentity, type IdentityFixture } from "@/test/identity-fixture";
import { sendEmailLink, signIn, signUp, startPhoneSignIn, verifyPhoneCode } from "./actions";

vi.mock("next/headers", async () => ({
  ...(await import("@/test/fake-cookies")).nextHeadersMock(),
  headers: () => Promise.resolve(new Headers({ host: "app.example.test" })),
}));

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

function form(entries: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

async function sessionCookie() {
  const cookie = fakeCookies.written("cw_session");
  return cookie === undefined ? null : decryptSession(cookie.value, KEY);
}

async function pendingCookie() {
  const cookie = fakeCookies.written("cw_pending");
  return cookie === undefined || cookie.value === "" ? null : decryptPending(cookie.value, KEY);
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

describe("signIn (the development persona)", () => {
  it("makes the persona at identity, exchanges it and redirects to the role's home", async () => {
    const promise = signIn(
      IDLE,
      form({ tenantKind: "internal", roles: ["analyst"], displayName: "Example analyst" }),
    );
    await expect(promise).rejects.toMatchObject({ href: "/admin" });
    const cookie = fakeCookies.written("cw_session");
    expect(cookie?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: "lax" });
    const claims = await sessionCookie();
    expect(claims).toMatchObject({
      tenantKind: "internal",
      roles: ["analyst"],
      displayName: "Example analyst",
      mfa: true,
      provider: "fake",
      sv: 0,
    });
    expect(claims?.cwToken).toBeDefined();
    expect(claims?.providerRefreshToken).toMatch(/^fake\.v1\./);
    expect(claims && claims.expiresAt - claims.issuedAt).toBe(28_800);
    expect(identity.requests.map((request) => request.pathname)).toEqual([
      "/v1/identity/dev/provider-tokens",
      "/v1/identity/sessions",
    ]);
    const persona = identity.requests[0]?.body as Record<string, unknown>;
    expect(persona).toMatchObject({ aal: "aal2", tenant_kind: "internal", roles: ["analyst"] });
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

  it("returns field errors from the adapter without calling identity", async () => {
    const state = await signIn(
      IDLE,
      form({ tenantKind: "business", roles: ["analyst"], displayName: "" }),
    );
    expect(state).toEqual({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:web-provider-invalid-contact",
        title: "Check the phone number or email address",
        correlationId: "",
      },
      fieldErrors: {
        displayName: ["Enter a display name."],
        roles: ["A business tenant cannot hold analyst; it allows owner, staff, compliance_lead."],
      },
    });
    expect(fakeCookies.written("cw_session")).toBeUndefined();
    expect(identity.requests).toHaveLength(0);
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

  it("shows identity's refusal of a persona as the problem", async () => {
    const owner = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    identity.bump(owner.id, { disabled: true });
    identity.fetchImpl = async () =>
      new Response(
        JSON.stringify({
          type: "urn:compliancewatch:problem:identity-last-admin",
          title: "Tenant would lose its last admin",
          status: 409,
        }),
        { status: 409, headers: { "content-type": "application/problem+json" } },
      );
    vi.stubGlobal("fetch", identity.fetchImpl);
    const state = await signIn(
      IDLE,
      form({ tenantKind: "business", roles: ["staff"], displayName: "Example owner" }),
    );
    expect(state.status).toBe("error");
    if (state.status === "error") expect(state.problem?.type).toContain("identity-last-admin");
  });
});

describe("the phone steps", () => {
  it("moves to the code step with the normalised number, and names a bad one", async () => {
    const started = await startPhoneSignIn(IDLE, form({ phone: "98765 43210", next: "/account" }));
    expect(started).toEqual({ status: "ok", value: { step: "code", phone: PHONE } });
    expect(identity.requests).toHaveLength(0);
    expect(await startPhoneSignIn(IDLE, form({ phone: "12" }))).toEqual({
      status: "error",
      fieldErrors: {
        phone: ["Enter a mobile number with its country code, such as +919876543210."],
      },
    });
    expect(await startPhoneSignIn(IDLE, form({}))).toEqual({
      status: "error",
      fieldErrors: { phone: ["Enter your mobile number."] },
    });
  });

  it("verifies the code and sends a new person to sign up with the pending cookie", async () => {
    const promise = verifyPhoneCode(IDLE, form({ phone: PHONE, code: "123456", next: "/account" }));
    await expect(promise).rejects.toMatchObject({ href: "/sign-up" });
    const pending = await pendingCookie();
    expect(pending?.contact).toEqual({ phone: PHONE });
    expect(pending?.next).toBe("/account");
    expect(pending?.session.aal).toBe("aal1");
    expect(fakeCookies.written("cw_session")).toBeUndefined();
  });

  it("signs a known person in and clears the pending cookie", async () => {
    identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    fakeCookies.set("cw_pending", "stale");
    const promise = verifyPhoneCode(IDLE, form({ phone: PHONE, code: "123456" }));
    await expect(promise).rejects.toMatchObject({ href: "/businesses" });
    expect((await sessionCookie())?.displayName).toBe("Example owner");
    expect(fakeCookies.written("cw_pending")?.options.maxAge).toBe(0);
  });

  it("sends a role that needs a second factor to verify it, and refuses a disabled person", async () => {
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "ca_firm",
      roles: ["ca_admin"],
    });
    await expect(
      verifyPhoneCode(IDLE, form({ phone: PHONE, code: "123456", next: "/settings/team" })),
    ).rejects.toMatchObject({ href: "/account/mfa?next=%2Fsettings%2Fteam" });
    expect((await pendingCookie())?.next).toBe("/settings/team");
    identity.bump(user.id, { disabled: true });
    const refused = await verifyPhoneCode(IDLE, form({ phone: PHONE, code: "123456" }));
    expect(refused).toEqual({
      status: "error",
      formErrors: ["This account was disabled by a tenant admin, so it cannot sign in."],
    });
  });

  it("names a code that is not six digits", async () => {
    expect(await verifyPhoneCode(IDLE, form({ phone: PHONE, code: "12" }))).toEqual({
      status: "error",
      fieldErrors: { code: ["Enter the 6 digits of the code."] },
    });
  });
});

describe("sendEmailLink", () => {
  it("asks the provider for the link to this deployment's callback and shows the email-sent page", async () => {
    const promise = sendEmailLink(IDLE, form({ email: "Owner@Example.test", next: "/account" }));
    await expect(promise).rejects.toMatchObject({ href: "/sign-in/email-sent" });
    // The fake adapter sent nothing: the token it would have mailed waits in the pending cookie.
    const pending = await pendingCookie();
    expect(pending?.contact).toEqual({ email: "owner@example.test" });
    expect(pending?.next).toBe("/account");
    expect(pending?.session.accessToken.split(".")).toHaveLength(3);
    expect(await sendEmailLink(IDLE, form({ email: "nope" }))).toEqual({
      status: "error",
      fieldErrors: { email: ["Enter an email address such as name@example.com."] },
    });
  });
});

describe("signUp", () => {
  async function pendingFor(
    contact: { phone: string },
    aal: "aal1" | "aal2" = "aal1",
    next?: string,
  ) {
    const token = identity.providerToken(contact, aal);
    fakeCookies.set(
      "cw_pending",
      await encryptPending(
        {
          provider: "fake",
          session: {
            accessToken: token,
            refreshToken: "fake.v1.x",
            expiresAt: 0,
            aal,
            subject: "s",
          },
          contact,
          ...(next === undefined ? {} : { next }),
        },
        KEY,
      ),
    );
  }

  it("creates a business and lands its owner on onboarding", async () => {
    await pendingFor({ phone: PHONE });
    const promise = signUp(
      IDLE,
      form({ kind: "business", name: "Example Traders", displayName: "Example owner" }),
    );
    await expect(promise).rejects.toMatchObject({ href: "/onboarding" });
    const claims = await sessionCookie();
    expect(claims).toMatchObject({
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    expect(identity.tenants.get(claims?.tenantId as string)?.name).toBe("Example Traders");
  });

  it("keeps a CA firm's form in the pending cookie and sends its admin to verify the factor", async () => {
    await pendingFor({ phone: PHONE }, "aal1", "/businesses");
    const promise = signUp(IDLE, form({ kind: "ca_firm", name: "Example CA", displayName: "" }));
    await expect(promise).rejects.toMatchObject({ href: "/account/mfa?next=%2Fbusinesses" });
    const pending = await pendingCookie();
    expect(pending?.signUp).toEqual({ kind: "ca_firm", name: "Example CA", displayName: "" });
    expect(identity.tenants.size).toBe(0);
  });

  it("names the fields, returns a registered person to sign-in and an expired wait to start", async () => {
    await pendingFor({ phone: PHONE });
    expect(await signUp(IDLE, form({ kind: "club", name: " " }))).toEqual({
      status: "error",
      fieldErrors: { kind: ["Choose the kind of account."], name: ["Enter a name."] },
    });
    identity.provision({ contact: { phone: PHONE }, kind: "business", roles: ["owner"] });
    await expect(signUp(IDLE, form({ kind: "business", name: "x" }))).rejects.toMatchObject({
      href: "/sign-in?error=registered",
    });
    fakeCookies.reset();
    await expect(signUp(IDLE, form({ kind: "business", name: "x" }))).rejects.toMatchObject({
      href: "/sign-in?error=pending-expired",
    });
  });
});
