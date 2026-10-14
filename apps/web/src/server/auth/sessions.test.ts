// @vitest-environment node
import { describe, expect, it } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { fakeFetch, problemResponse } from "@/test/fake-fetch";
import { fakeIdentity } from "@/test/identity-fixture";
import { loadEnv } from "../env";
import { isProblem } from "../result";
import type { ProviderSession } from "./provider";
import {
  PROVIDER_TOKEN_MARGIN_SECONDS,
  claimsFromMe,
  claimsFromSessionOut,
  exchangeSession,
  providerSessionOf,
  readMe,
  signUpTenant,
  withProviderSession,
  type SessionOut,
} from "./sessions";

const NOW = new Date("2026-09-29T10:00:00Z");
const PHONE = "+919876543210";
const env = loadEnv({ CW_WEB_ENV: "test", CW_WEB_AUTH_PROVIDER: "fake" });

function providerSession(
  identity: ReturnType<typeof fakeIdentity>,
  aal: "aal1" | "aal2" = "aal1",
): ProviderSession {
  return {
    accessToken: identity.providerToken({ phone: PHONE }, aal),
    refreshToken: "fake.v1.refresh",
    expiresAt: 1_790_679_600,
    aal,
    subject: "subject:+919876543210",
  };
}

describe("claimsFromSessionOut", () => {
  const out: SessionOut = {
    access_token: "cw.user.0",
    token_type: "Bearer",
    expires_in: 600,
    tenant_id: "tenant-1",
    tenant_kind: "ca_firm",
    user_id: "user-1",
    display_name: "  Example admin ",
    roles: ["ca_admin", "compliance_lead"],
    mfa: true,
    session_version: 2,
  };
  const provider: ProviderSession = {
    accessToken: "p",
    refreshToken: "r",
    expiresAt: 1,
    aal: "aal2",
    subject: "s",
  };

  it("fills the cookie's claims from the exchange and the provider session", () => {
    const claims = claimsFromSessionOut(out, provider, "supabase", NOW, 28_800);
    expect(claims).toEqual({
      userId: "user-1",
      tenantId: "tenant-1",
      tenantKind: "ca_firm",
      roles: ["ca_admin", "compliance_lead"],
      displayName: "Example admin",
      mfa: true,
      sv: 2,
      provider: "supabase",
      ...sessionWindow(NOW, 28_800),
      cwToken: "cw.user.0",
      cwTokenExpiresAt: 1_790_676_000 + 600,
      providerRefreshToken: "r",
      providerAccessToken: "p",
      providerAccessExpiresAt: 1,
      checkedAt: 1_790_676_000,
    });
  });

  it("hands the provider session back from the claims while its token has the margin left", () => {
    const claims = claimsFromSessionOut(
      out,
      { ...provider, expiresAt: 1_790_676_000 + 300 },
      "supabase",
      NOW,
      28_800,
    );
    if (claims === null) throw new Error("no claims");
    expect(providerSessionOf(claims, 1_790_676_000)).toEqual({
      accessToken: "p",
      refreshToken: "r",
      expiresAt: 1_790_676_000 + 300,
      aal: "aal2",
      subject: "",
    });
    expect(providerSessionOf({ ...claims, mfa: false }, 1_790_676_000)?.aal).toBe("aal1");
    const edge = 1_790_676_000 + 300 - PROVIDER_TOKEN_MARGIN_SECONDS;
    expect(providerSessionOf(claims, edge)).not.toBeNull();
    expect(providerSessionOf(claims, edge + 1)).toBeNull();
    expect(providerSessionOf(claims, 1_790_676_000, 301)).toBeNull();
    expect(providerSessionOf({ ...claims, providerAccessToken: undefined }, 0)).toBeNull();
    expect(providerSessionOf({ ...claims, providerRefreshToken: undefined }, 0)).toBeNull();
    const rotated = withProviderSession(
      { ...claims, refreshNotBefore: 5 },
      { accessToken: "p2", refreshToken: "r2", expiresAt: 9, aal: "aal2", subject: "s" },
    );
    expect(rotated).toMatchObject({
      providerAccessToken: "p2",
      providerRefreshToken: "r2",
      providerAccessExpiresAt: 9,
      cwToken: "cw.user.0",
    });
    expect(rotated).not.toHaveProperty("refreshNotBefore");
  });

  it("names a person without a name by their id and refuses an unreadable answer", () => {
    expect(
      claimsFromSessionOut({ ...out, display_name: "" }, provider, "fake", NOW, 1)?.displayName,
    ).toBe("User user-1");
    expect(
      claimsFromSessionOut({ ...out, tenant_kind: "club" as never }, provider, "fake", NOW, 1),
    ).toBeNull();
    expect(claimsFromSessionOut({ ...out, roles: [] }, provider, "fake", NOW, 1)).toBeNull();
  });
});

describe("exchangeSession", () => {
  it("signs a known person in with everything the cookie needs", async () => {
    const identity = fakeIdentity();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    // One session for the call and the assertion: a token minted a second later differs.
    const session = providerSession(identity);
    const outcome = await exchangeSession(session, "fake", {
      env,
      fetchImpl: identity.fetchImpl,
      now: NOW,
    });
    expect(outcome.kind).toBe("signed-in");
    if (outcome.kind !== "signed-in") return;
    expect(outcome.claims).toMatchObject({
      userId: user.id,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      sv: 0,
      provider: "fake",
      cwToken: identity.accessToken(user),
      providerRefreshToken: "fake.v1.refresh",
      providerAccessToken: session.accessToken,
      providerAccessExpiresAt: session.expiresAt,
    });
    expect(outcome.claims.expiresAt - outcome.claims.issuedAt).toBe(28_800);
    expect(identity.requests[0]?.headers.authorization).toBeUndefined();
    expect(identity.requests[0]?.body).toEqual({ provider_token: session.accessToken });
  });

  it("maps identity's answers to the steps of the flow", async () => {
    const identity = fakeIdentity();
    const deps = { env, fetchImpl: identity.fetchImpl, now: NOW };
    expect((await exchangeSession(providerSession(identity), "fake", deps)).kind).toBe(
      "needs-sign-up",
    );
    const admin = identity.provision({
      contact: { phone: PHONE },
      kind: "internal",
      roles: ["admin"],
    });
    expect((await exchangeSession(providerSession(identity), "fake", deps)).kind).toBe("needs-mfa");
    expect((await exchangeSession(providerSession(identity, "aal2"), "fake", deps)).kind).toBe(
      "signed-in",
    );
    identity.bump(admin.id, { disabled: true });
    expect((await exchangeSession(providerSession(identity, "aal2"), "fake", deps)).kind).toBe(
      "user-disabled",
    );
    const tenant = identity.tenants.get(admin.tenantId);
    if (tenant !== undefined) tenant.status = "deletion_requested";
    admin.status = "active";
    expect((await exchangeSession(providerSession(identity, "aal2"), "fake", deps)).kind).toBe(
      "tenant-deleting",
    );
  });

  it("reports an unavailable provider, a network failure and any other refusal", async () => {
    const unavailable = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/sessions",
        status: 503,
        problem: { type: "urn:compliancewatch:problem:identity-provider-unavailable" },
      },
    ]);
    const session: ProviderSession = {
      accessToken: "t",
      refreshToken: "r",
      expiresAt: 1,
      aal: "aal1",
      subject: "s",
    };
    const down = await exchangeSession(session, "supabase", {
      env,
      fetchImpl: unavailable.fetchImpl,
    });
    expect(down.kind).toBe("provider-unavailable");
    const refused = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/sessions",
        status: 401,
        problem: { type: "urn:compliancewatch:problem:identity-provider-token-invalid" },
      },
    ]);
    const bad = await exchangeSession(session, "supabase", { env, fetchImpl: refused.fetchImpl });
    expect(bad.kind).toBe("failed");
    if (bad.kind === "failed")
      expect(isProblem(bad.error, "identity-provider-token-invalid")).toBe(true);
    const gone = fakeFetch(() => {
      throw new TypeError("fetch failed");
    });
    expect(
      (await exchangeSession(session, "supabase", { env, fetchImpl: gone.fetchImpl })).kind,
    ).toBe("provider-unavailable");
  });
});

describe("signUpTenant", () => {
  it("creates the tenant with its first user's session, and refuses a registered person", async () => {
    const identity = fakeIdentity();
    const deps = { env, fetchImpl: identity.fetchImpl, now: NOW };
    const outcome = await signUpTenant(
      providerSession(identity),
      "fake",
      { kind: "business", name: "Example Traders", displayName: "Example person" },
      deps,
    );
    expect(outcome.kind).toBe("signed-in");
    if (outcome.kind !== "signed-in") return;
    expect(outcome.claims).toMatchObject({
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example person",
    });
    expect(identity.requests[0]?.body).toEqual({
      kind: "business",
      name: "Example Traders",
      provider_token: providerSession(identity).accessToken,
      display_name: "Example person",
    });
    const again = await signUpTenant(
      providerSession(identity),
      "fake",
      { kind: "ca_firm", name: "x", displayName: "" },
      deps,
    );
    expect(again.kind).toBe("subject-registered");
    const other = {
      ...providerSession(identity),
      accessToken: identity.providerToken({ phone: "+919812345678" }),
    };
    const needsMfa = await signUpTenant(
      other,
      "fake",
      { kind: "ca_firm", name: "Example CA", displayName: "" },
      deps,
    );
    expect(needsMfa.kind).toBe("needs-mfa");
  });
});

describe("readMe", () => {
  function claims(identity: ReturnType<typeof fakeIdentity>, userId: string): SessionClaims {
    const user = identity.users.get(userId);
    if (user === undefined) throw new Error("no user");
    return {
      userId,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "x",
      mfa: false,
      sv: user.sessionVersion,
      provider: "fake",
      ...sessionWindow(NOW, 3600),
      cwToken: identity.accessToken(user),
      checkedAt: 0,
    };
  }

  it("reads the user with the bearer and brings the claims up to date", async () => {
    const identity = fakeIdentity();
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
      displayName: "Example owner",
    });
    const current = claims(identity, user.id);
    const read = await readMe(current, { env, fetchImpl: identity.fetchImpl });
    expect(read.kind).toBe("ok");
    expect(identity.requests[0]?.headers.authorization).toBe(
      `Bearer ${identity.accessToken(user)}`,
    );
    expect(identity.requests[0]?.headers["x-tenant-id"]).toBe(user.tenantId);
    if (read.kind !== "ok") return;
    identity.bump(user.id, { roles: ["owner", "compliance_lead"] });
    const revoked = await readMe(current, { env, fetchImpl: identity.fetchImpl });
    expect(revoked.kind).toBe("revoked");
    const fresh = claims(identity, user.id);
    const again = await readMe(fresh, { env, fetchImpl: identity.fetchImpl });
    expect(again.kind).toBe("ok");
    if (again.kind !== "ok") return;
    const updated = claimsFromMe(fresh, again.me, NOW);
    expect(updated.roles).toEqual(["compliance_lead", "owner"]);
    expect(updated.sv).toBe(1);
    expect(updated.displayName).toBe("Example owner");
    expect(updated.checkedAt).toBe(1_790_676_000);
  });

  it("knows identity in header mode cannot answer, and reports other failures", async () => {
    const identity = fakeIdentity({ headerMode: true });
    const user = identity.provision({
      contact: { phone: PHONE },
      kind: "business",
      roles: ["owner"],
    });
    const read = await readMe(claims(identity, user.id), { env, fetchImpl: identity.fetchImpl });
    expect(read.kind).toBe("unverifiable");
    const noToken = await readMe({ tenantId: "t" }, { env, fetchImpl: identity.fetchImpl });
    expect(noToken.kind).toBe("unverifiable");
    const broken = fakeFetch(() => problemResponse(500));
    const failed = await readMe(
      { ...claims(identity, user.id) },
      { env, fetchImpl: broken.fetchImpl },
    );
    expect(failed.kind).toBe("failed");
  });
});
