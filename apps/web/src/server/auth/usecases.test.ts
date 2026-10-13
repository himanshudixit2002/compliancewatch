// @vitest-environment node
import { describe, expect, it } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { fakeIdentity } from "@/test/identity-fixture";
import { loadEnv } from "../env";
import { err, type Result } from "../result";
import { FakeAuthProvider } from "./fake";
import type { PendingSignIn } from "./pending";
import { providerFailure, type AuthProvider, type ProviderSession } from "./provider";
import {
  completeMfa,
  completeSignUp,
  keepSessionCurrent,
  needsRecheck,
  needsRefresh,
  refreshSession,
  signInWithProviderSession,
} from "./usecases";

const NOW = new Date("2026-09-29T10:00:00Z");
const AT = Math.floor(NOW.getTime() / 1000);
const PHONE = "+919876543210";
const env = loadEnv({ CW_WEB_ENV: "test", CW_WEB_AUTH_PROVIDER: "fake" });

function setup() {
  const identity = fakeIdentity();
  const provider = new FakeAuthProvider(env, { fetchImpl: identity.fetchImpl });
  const deps = { env, fetchImpl: identity.fetchImpl, now: NOW };
  return { identity, provider, deps };
}

/**
 * A provider that rotates its refresh token like GoTrue: every refresh answers a new one and a
 * token already used is refused (the session family revoked), which the fake never does.
 */
function rotating(inner: AuthProvider): AuthProvider & { issued: number; used: string[] } {
  const used: string[] = [];
  let issued = 0;
  const refresh = async (token: string): Promise<Result<ProviderSession>> => {
    if (used.includes(token)) {
      return err(providerFailure("expired", "Invalid Refresh Token: Already Used"));
    }
    used.push(token);
    const session = await inner.refresh(token.startsWith("rot-") ? ROTATED_INNER : token);
    if (!session.ok) return session;
    issued += 1;
    wrapper.issued = issued;
    return { ok: true, value: { ...session.value, refreshToken: `rot-${issued}` } };
  };
  const wrapper = Object.assign(Object.create(inner) as AuthProvider, {
    refresh,
    issued: 0,
    used,
  });
  return wrapper;
}

/** What the rotating provider refreshes with underneath: the fake's own stateless token. */
const ROTATED_INNER =
  "fake.v1." +
  Buffer.from(JSON.stringify({ contact: { phone: PHONE }, aal: "aal1" })).toString("base64url");

describe("signInWithProviderSession", () => {
  it("goes to sign-up, then mfa, then a session, keeping next in the pending cookie", async () => {
    const { identity, provider, deps } = setup();
    const verified = await provider.verifyPhoneOtp(PHONE, "123456");
    if (!verified.ok) throw new Error("no session");
    const ctx = { provider, contact: { phone: PHONE }, next: "/settings/team", deps };
    const first = await signInWithProviderSession(ctx, verified.value);
    expect(first.kind).toBe("sign-up");
    if (first.kind !== "sign-up") return;
    expect(first.pending).toEqual({
      provider: "fake",
      session: verified.value,
      contact: { phone: PHONE },
      next: "/settings/team",
    });
    identity.provision({ contact: { phone: PHONE }, kind: "ca_firm", roles: ["ca_admin"] });
    const second = await signInWithProviderSession(ctx, verified.value);
    expect(second.kind).toBe("mfa");
    const aal2 = await provider.mfa.verify(verified.value, "fake-confirm", "fake-confirm", "");
    if (!aal2.ok) throw new Error("no aal2");
    const third = await signInWithProviderSession(ctx, aal2.value);
    expect(third.kind).toBe("session");
    if (third.kind === "session") expect(third.claims.mfa).toBe(true);
  });

  it("reports a disabled person and a tenant being deleted as refusals", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const verified = await provider.verifyPhoneOtp(PHONE, "123456");
    if (!verified.ok) throw new Error("no session");
    const ctx = { provider, contact: { phone: PHONE }, deps };
    identity.bump(user.id, { disabled: true });
    expect(await signInWithProviderSession(ctx, verified.value)).toEqual({
      kind: "refused",
      reason: "user-disabled",
    });
  });
});

describe("completeSignUp and completeMfa", () => {
  it("creates a business at once, and a CA firm after the second factor", async () => {
    const { provider, deps } = setup();
    const verified = await provider.verifyPhoneOtp(PHONE, "123456");
    if (!verified.ok) throw new Error("no session");
    const ctx = { provider, contact: { phone: PHONE }, deps };
    const pending: PendingSignIn = {
      provider: "fake",
      session: verified.value,
      contact: { phone: PHONE },
    };
    const business = await completeSignUp(ctx, pending, {
      kind: "business",
      name: "Example Traders",
      displayName: "Example owner",
    });
    expect(business.kind).toBe("session");
    if (business.kind === "session") expect(business.claims.roles).toEqual(["owner"]);
    const other = await provider.verifyPhoneOtp("+919812345678", "123456");
    if (!other.ok) throw new Error("no session");
    const firm = await completeSignUp(
      { ...ctx, contact: { phone: "+919812345678" } },
      { provider: "fake", session: other.value, contact: { phone: "+919812345678" } },
      { kind: "ca_firm", name: "Example CA", displayName: "Example admin" },
    );
    expect(firm.kind).toBe("mfa");
    if (firm.kind !== "mfa") return;
    expect(firm.pending.signUp).toEqual({
      kind: "ca_firm",
      name: "Example CA",
      displayName: "Example admin",
    });
    const aal2 = await provider.mfa.verify(other.value, "fake-confirm", "fake-confirm", "");
    if (!aal2.ok) throw new Error("no aal2");
    const done = await completeMfa(ctx, firm.pending, aal2.value);
    expect(done.kind).toBe("session");
    if (done.kind === "session") {
      expect(done.claims.roles).toEqual(["ca_admin"]);
      expect(done.claims.mfa).toBe(true);
      expect(done.claims.displayName).toBe("Example admin");
    }
  });

  it("refuses a sign-up for a person who is a user already", async () => {
    const { identity, provider, deps } = setup();
    identity.provision({ contact: { phone: PHONE }, kind: "business", roles: ["owner"] });
    const verified = await provider.verifyPhoneOtp(PHONE, "123456");
    if (!verified.ok) throw new Error("no session");
    const step = await completeSignUp(
      { provider, contact: { phone: PHONE }, deps },
      { provider: "fake", session: verified.value, contact: { phone: PHONE } },
      { kind: "business", name: "x", displayName: "" },
    );
    expect(step).toEqual({ kind: "refused", reason: "subject-registered" });
  });
});

describe("keeping a session current", () => {
  function claimsFor(
    identity: ReturnType<typeof fakeIdentity>,
    userId: string,
    overrides: Partial<SessionClaims> = {},
  ): SessionClaims {
    const user = identity.users.get(userId);
    if (user === undefined) throw new Error("no user");
    return {
      userId: user.id,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: [...user.roles],
      displayName: user.displayName,
      mfa: false,
      sv: user.sessionVersion,
      provider: "fake",
      ...sessionWindow(new Date((AT - 3600) * 1000), 28_800),
      cwToken: identity.accessToken(user),
      cwTokenExpiresAt: AT + 500,
      providerRefreshToken:
        "fake.v1." +
        Buffer.from(JSON.stringify({ contact: { phone: PHONE }, aal: "aal1" })).toString(
          "base64url",
        ),
      checkedAt: AT,
      analyticsConsent: true,
      ...overrides,
    };
  }

  it("decides refresh and recheck from the margins", () => {
    const { identity } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const fresh = claimsFor(identity, user.id);
    expect(needsRefresh(fresh, AT, env)).toBe(false);
    expect(needsRefresh({ ...fresh, cwTokenExpiresAt: AT + 119 }, AT, env)).toBe(true);
    expect(
      needsRefresh({ ...fresh, cwToken: undefined, cwTokenExpiresAt: undefined }, AT, env),
    ).toBe(false);
    expect(needsRefresh({ ...fresh, providerAccessExpiresAt: AT + 119 }, AT, env)).toBe(true);
    expect(needsRefresh({ ...fresh, providerAccessExpiresAt: AT + 120 }, AT, env)).toBe(false);
    expect(
      needsRefresh({ ...fresh, cwTokenExpiresAt: AT + 10, refreshNotBefore: AT + 1 }, AT, env),
    ).toBe(false);
    expect(
      needsRefresh({ ...fresh, cwTokenExpiresAt: AT + 10, refreshNotBefore: AT }, AT, env),
    ).toBe(true);
    expect(needsRecheck(fresh, AT, env)).toBe(false);
    expect(needsRecheck(fresh, AT + 300, env)).toBe(true);
    expect(needsRecheck({ ...fresh, checkedAt: undefined }, AT, env)).toBe(true);
    const eager = loadEnv({
      CW_WEB_ENV: "test",
      CW_WEB_AUTH_PROVIDER: "fake",
      CW_WEB_SESSION_RECHECK_SECONDS: "0",
    });
    expect(needsRecheck(fresh, AT, eager)).toBe(true);
  });

  it("leaves a current session alone", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    expect(await keepSessionCurrent(provider, claimsFor(identity, user.id), deps)).toEqual({
      kind: "unchanged",
    });
    expect(identity.requests).toHaveLength(0);
  });

  it("refreshes a token about to expire through the provider and keeps the session's window", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    const claims = claimsFor(identity, user.id, { cwTokenExpiresAt: AT + 30 });
    const outcome = await keepSessionCurrent(provider, claims, deps);
    expect(outcome.kind).toBe("updated");
    if (outcome.kind !== "updated") return;
    expect(outcome.claims.cwToken).toBe(identity.accessToken(user));
    expect(outcome.claims.cwTokenExpiresAt).toBe(AT + 600);
    expect(outcome.claims.issuedAt).toBe(claims.issuedAt);
    expect(outcome.claims.expiresAt).toBe(claims.expiresAt);
    expect(outcome.claims.analyticsConsent).toBe(true);
    expect(outcome.claims.checkedAt).toBe(AT);
    expect(identity.requests.map((request) => request.pathname)).toEqual([
      "/v1/identity/dev/provider-tokens",
      "/v1/identity/sessions",
    ]);
    const direct = await refreshSession(
      provider,
      { ...claims, providerRefreshToken: undefined },
      deps,
    );
    expect(direct.ok).toBe(false);
  });

  it("re-exchanges the cookie's provider token while it lasts, refreshing only near its expiry", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const token = identity.providerToken({ phone: PHONE });
    const lasting = claimsFor(identity, user.id, {
      cwTokenExpiresAt: AT + 30,
      providerAccessToken: token,
      providerAccessExpiresAt: AT + 3600,
    });
    const kept = await keepSessionCurrent(provider, lasting, deps);
    expect(kept.kind).toBe("updated");
    if (kept.kind !== "updated") return;
    expect(kept.claims.providerAccessToken).toBe(token);
    expect(kept.claims.providerRefreshToken).toBe(lasting.providerRefreshToken);
    expect(identity.requests.map((request) => request.pathname)).toEqual(["/v1/identity/sessions"]);
    identity.requests.length = 0;
    const nearly = { ...lasting, providerAccessExpiresAt: AT + 119 };
    const refreshed = await keepSessionCurrent(provider, nearly, deps);
    expect(refreshed.kind).toBe("updated");
    if (refreshed.kind !== "updated") return;
    // The fake mints the same token within a second; the provider call and the new expiry show it.
    expect(refreshed.claims.providerAccessExpiresAt).toBeGreaterThan(AT + 119);
    expect(identity.requests.map((request) => request.pathname)).toEqual([
      "/v1/identity/dev/provider-tokens",
      "/v1/identity/sessions",
    ]);
  });

  it("writes the rotated refresh token back, so the next refresh uses it and never the spent one", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const gotrue = rotating(provider);
    const stale = claimsFor(identity, user.id, {
      cwTokenExpiresAt: AT + 30,
      providerAccessToken: "old",
      providerAccessExpiresAt: AT + 10,
      providerRefreshToken: "rot-0",
    });
    const first = await keepSessionCurrent(gotrue, stale, deps);
    expect(first.kind).toBe("updated");
    if (first.kind !== "updated") return;
    expect(first.claims.providerRefreshToken).toBe("rot-1");
    const again = { ...first.claims, providerAccessExpiresAt: AT + 10, cwTokenExpiresAt: AT + 30 };
    const second = await keepSessionCurrent(gotrue, again, deps);
    expect(second.kind).toBe("updated");
    if (second.kind === "updated") expect(second.claims.providerRefreshToken).toBe("rot-2");
    expect(gotrue.used).toEqual(["rot-0", "rot-1"]);
    // The cookie that missed the first write still holds rot-0: GoTrue has spent it.
    expect(await keepSessionCurrent(gotrue, stale, deps)).toEqual({ kind: "revoked" });
  });

  it("keeps the rotated pair when identity does not answer after the provider refreshed", async () => {
    const { identity, provider } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const gotrue = rotating(provider);
    const identityDown = {
      env,
      now: NOW,
      fetchImpl: async (input: Request, init?: RequestInit) => {
        if (new URL(input.url).pathname === "/v1/identity/sessions") {
          throw new TypeError("fetch failed");
        }
        return identity.fetchImpl(input, init);
      },
    };
    const stale = claimsFor(identity, user.id, {
      cwTokenExpiresAt: AT + 30,
      providerAccessToken: "old",
      providerAccessExpiresAt: AT + 10,
      providerRefreshToken: "rot-0",
    });
    const outcome = await keepSessionCurrent(gotrue, stale, identityDown);
    expect(outcome.kind).toBe("deferred");
    if (outcome.kind !== "deferred") return;
    expect(outcome.claims.providerRefreshToken).toBe("rot-1");
    expect(outcome.claims.providerAccessToken).not.toBe("old");
    expect(outcome.claims.cwToken).toBe(stale.cwToken);
    // Identity back: the kept pair refreshes; the pair a lost write would have left is spent.
    const recovered = await keepSessionCurrent(
      gotrue,
      { ...outcome.claims, providerAccessExpiresAt: AT + 10 },
      { env, now: NOW, fetchImpl: identity.fetchImpl },
    );
    expect(recovered.kind).toBe("updated");
    expect(await keepSessionCurrent(gotrue, stale, identityDown)).toEqual({ kind: "revoked" });
  });

  it("waits out a provider rate limit instead of signing the person out", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const limited = Object.assign(Object.create(provider) as AuthProvider, {
      refresh: () =>
        Promise.resolve(
          err(providerFailure("rate_limited", "Too many requests", { retryAfterSeconds: 45 })),
        ),
    });
    const stale = claimsFor(identity, user.id, {
      cwTokenExpiresAt: AT + 30,
      providerAccessToken: "old",
      providerAccessExpiresAt: AT + 10,
    });
    const outcome = await keepSessionCurrent(limited, stale, deps);
    expect(outcome.kind).toBe("deferred");
    if (outcome.kind !== "deferred") return;
    expect(outcome.claims.refreshNotBefore).toBe(AT + 45);
    expect(outcome.claims.providerRefreshToken).toBe(stale.providerRefreshToken);
    expect(needsRefresh(outcome.claims, AT + 44, env)).toBe(false);
    expect(needsRefresh(outcome.claims, AT + 45, env)).toBe(true);
    const unnamed = Object.assign(Object.create(provider) as AuthProvider, {
      refresh: () => Promise.resolve(err(providerFailure("rate_limited"))),
    });
    const later = await keepSessionCurrent(unnamed, stale, deps);
    expect(later.kind === "deferred" && later.claims.refreshNotBefore).toBe(AT + 30);
  });

  it("re-reads /me once the last read is old and takes the roles and version from it", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    const claims = claimsFor(identity, user.id, { checkedAt: AT - 301 });
    user.roles = ["owner", "compliance_lead"];
    const outcome = await keepSessionCurrent(provider, claims, deps);
    expect(outcome.kind).toBe("updated");
    if (outcome.kind !== "updated") return;
    expect(outcome.claims.roles).toEqual(["compliance_lead", "owner"]);
    expect(outcome.claims.checkedAt).toBe(AT);
    expect(identity.requests.map((request) => request.pathname)).toEqual(["/v1/identity/me"]);
  });

  it("signs out a session identity revoked, on the refresh or on the re-read", async () => {
    const { identity, provider, deps } = setup();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const stale = claimsFor(identity, user.id, { checkedAt: AT - 301 });
    identity.bump(user.id, { roles: ["owner", "staff"] });
    expect(await keepSessionCurrent(provider, stale, deps)).toEqual({ kind: "revoked" });
    identity.bump(user.id, { disabled: true });
    const expiring = claimsFor(identity, user.id, { cwTokenExpiresAt: AT + 10 });
    expect(await keepSessionCurrent(provider, expiring, deps)).toEqual({ kind: "revoked" });
  });

  it("defers when identity cannot answer or reads no token, noting the attempt", async () => {
    const identity = fakeIdentity({ headerMode: true });
    const provider = new FakeAuthProvider(env, { fetchImpl: identity.fetchImpl });
    const deps = { env, fetchImpl: identity.fetchImpl, now: NOW };
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const outcome = await keepSessionCurrent(
      provider,
      claimsFor(identity, user.id, { checkedAt: AT - 400 }),
      deps,
    );
    expect(outcome.kind).toBe("deferred");
    if (outcome.kind === "deferred") {
      expect(outcome.claims.checkedAt).toBe(AT);
      expect(outcome.error.problem?.type).toContain("auth-token-required");
    }
    const down = new FakeAuthProvider(env, {
      fetchImpl: async () => {
        throw new TypeError("fetch failed");
      },
    });
    const expiring = claimsFor(identity, user.id, { cwTokenExpiresAt: AT + 10 });
    const refreshFailed = await keepSessionCurrent(down, expiring, {
      ...deps,
      fetchImpl: down["client"] ? undefined : undefined,
    });
    expect(["deferred", "revoked"]).toContain(refreshFailed.kind);
  });
});
