// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isUuid } from "@/shared/lib/identifiers";
import { claimsOf, fakeIdentity } from "@/test/identity-fixture";
import { EnvError, loadEnv } from "../env";
import { isProblem } from "../result";
import {
  DEV_INTERNAL_TENANT_ID,
  DISPLAY_NAME_MAX_LENGTH,
  FAKE_FACTOR_ID,
  FakeAuthProvider,
  PERSONA_EMAIL_DOMAIN,
  decodeFakeRefreshToken,
  encodeFakeRefreshToken,
  fakeUserId,
  personaEmail,
  uuidV5,
  validateFakeSignIn,
} from "./fake";
import { providerFailureKind, type AuthProvider, type DevPersonaInput } from "./provider";

const TENANT = "00000000-0000-4000-8000-000000000002";
const PHONE = "+919876543210";

const owner: DevPersonaInput = {
  tenantKind: "business",
  roles: ["owner"],
  displayName: "Example owner",
};

const localEnv = loadEnv({ CW_WEB_ENV: "local", CW_WEB_AUTH_PROVIDER: "fake" });

function provider() {
  const identity = fakeIdentity();
  return { identity, fake: new FakeAuthProvider(localEnv, { fetchImpl: identity.fetchImpl }) };
}

describe("uuidV5", () => {
  it("matches the RFC 4122 test vector", () => {
    const dns = "6ba7b810-9dad-11d1-80b4-00c04fd430c8";
    expect(uuidV5(dns, "www.example.com")).toBe("2ed6657d-e927-568b-95e1-2665a8aea6a2");
  });
});

describe("fakeUserId and personaEmail", () => {
  it("are the same person for the same name in the same tenant, whatever the case or spacing", () => {
    const id = fakeUserId(TENANT, "Example owner");
    expect(isUuid(id)).toBe(true);
    expect(fakeUserId(TENANT, "  example OWNER ")).toBe(id);
    expect(fakeUserId(TENANT, "Another name")).not.toBe(id);
    expect(fakeUserId("00000000-0000-4000-8000-000000000003", "Example owner")).not.toBe(id);
    expect(personaEmail(TENANT, "Example owner")).toBe(`${id}@${PERSONA_EMAIL_DOMAIN}`);
  });
});

describe("validateFakeSignIn", () => {
  it("accepts a well-formed input", () => {
    expect(validateFakeSignIn(owner)).toEqual({});
    expect(validateFakeSignIn({ ...owner, tenantId: TENANT })).toEqual({});
    expect(validateFakeSignIn({ ...owner, tenantId: "  " })).toEqual({});
  });

  it("names each field that fails", () => {
    expect(validateFakeSignIn({ ...owner, displayName: "  " })).toEqual({
      displayName: ["Enter a display name."],
    });
    expect(
      validateFakeSignIn({ ...owner, displayName: "x".repeat(DISPLAY_NAME_MAX_LENGTH + 1) })
        .displayName?.[0],
    ).toMatch(/at most 80/);
    expect(validateFakeSignIn({ ...owner, tenantId: "tenant-1" })).toEqual({
      tenantId: ["Enter a UUID, or leave it empty."],
    });
    expect(validateFakeSignIn({ ...owner, roles: [] })).toEqual({
      roles: ["Choose at least one role."],
    });
    expect(validateFakeSignIn({ ...owner, roles: ["analyst"] }).roles?.[0]).toBe(
      "A business tenant cannot hold analyst; it allows owner, staff, compliance_lead.",
    );
    expect(
      validateFakeSignIn({ ...owner, tenantKind: "ca_firm", roles: ["ca_admin", "owner"] })
        .roles?.[0],
    ).toMatch(/cannot hold owner/);
    expect(validateFakeSignIn({ ...owner, roles: ["monarch" as never] }).roles?.[0]).toBe(
      "Unknown role: monarch.",
    );
    expect(validateFakeSignIn({ ...owner, tenantKind: "club" as never })).toEqual({
      tenantKind: ["Choose a tenant kind."],
    });
    const many = validateFakeSignIn({ ...owner, displayName: "", tenantId: "x", roles: [] });
    expect(Object.keys(many).sort()).toEqual(["displayName", "roles", "tenantId"]);
  });
});

describe("the fake refresh token", () => {
  it("round-trips the contact and the level, and refuses anything else", () => {
    const token = encodeFakeRefreshToken({ phone: PHONE }, "aal2");
    expect(token.startsWith("fake.v1.")).toBe(true);
    expect(decodeFakeRefreshToken(token)).toEqual({ contact: { phone: PHONE }, aal: "aal2" });
    expect(decodeFakeRefreshToken("supabase-refresh")).toBeNull();
    expect(decodeFakeRefreshToken("fake.v1.!!!")).toBeNull();
    expect(decodeFakeRefreshToken(encodeFakeRefreshToken({}, "aal1"))).toBeNull();
  });
});

describe("FakeAuthProvider", () => {
  it("is refused outside local and test", () => {
    expect(() => new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "staging" }))).toThrow(EnvError);
    expect(() => new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "prod" }))).toThrow(
      /local and test only/,
    );
    const fake = new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "test" }));
    expect(fake.name).toBe("fake");
    expect(fake.methods).toEqual(["dev", "phone", "email"]);
    expect(fake.mfaMode).toBe("confirm");
  });

  it("signs in as a persona identity makes, at aal2 for the roles that need it", async () => {
    const { identity, fake } = provider();
    const session = await fake.signInAsPersona({
      tenantId: ` ${TENANT} `,
      tenantKind: "internal",
      roles: ["admin", "analyst", "admin"],
      displayName: "  Example admin ",
    });
    expect(session.ok).toBe(true);
    if (!session.ok) return;
    expect(session.value.aal).toBe("aal2");
    expect(claimsOf(session.value.accessToken)?.email).toBe(personaEmail(TENANT, "Example admin"));
    expect(decodeFakeRefreshToken(session.value.refreshToken)).toEqual({
      contact: { email: personaEmail(TENANT, "Example admin") },
      aal: "aal2",
    });
    const sent = identity.requests[0]?.body as Record<string, unknown>;
    expect(sent).toMatchObject({
      aal: "aal2",
      tenant_id: TENANT,
      tenant_kind: "internal",
      roles: ["analyst", "admin"],
      display_name: "Example admin",
    });
    expect(identity.tenants.get(TENANT)?.kind).toBe("internal");
    const staff = await fake.signInAsPersona({ ...owner, roles: ["staff"] });
    expect(staff.ok && staff.value.aal).toBe("aal1");
    expect(
      staff.ok &&
        isUuid(
          String(
            identity.requests[1]?.body &&
              (identity.requests[1].body as Record<string, unknown>).tenant_id,
          ),
        ),
    ).toBe(true);
  });

  it("puts a regulatory persona without a tenant id in the one development internal tenant", async () => {
    // identity's own constant: uuid5(NAMESPACE_URL, "urn:compliancewatch:dev:internal-tenant")
    expect(DEV_INTERNAL_TENANT_ID).toBe("cf42499e-2f75-5ecb-a1c0-bc82d8495ad2");
    const { identity, fake } = provider();
    const admin = await fake.signInAsPersona({
      tenantKind: "internal",
      roles: ["admin"],
      displayName: "Example admin",
    });
    const analyst = await fake.signInAsPersona({
      tenantKind: "internal",
      roles: ["analyst"],
      displayName: "Example analyst",
    });
    const again = await fake.signInAsPersona({
      tenantKind: "internal",
      roles: ["admin"],
      displayName: "Example admin",
    });
    expect([admin.ok, analyst.ok, again.ok]).toEqual([true, true, true]);
    for (const request of identity.requests) {
      expect(request.body).toMatchObject({ tenant_id: DEV_INTERNAL_TENANT_ID });
    }
    expect([...identity.tenants.keys()]).toEqual([DEV_INTERNAL_TENANT_ID]);
    expect(identity.tenants.get(DEV_INTERNAL_TENANT_ID)?.kind).toBe("internal");
    expect(identity.users.size).toBe(2);
    // A second internal tenant is identity's refusal, passed through.
    const other = await fake.signInAsPersona({
      tenantId: TENANT,
      tenantKind: "internal",
      roles: ["reviewer"],
      displayName: "Example reviewer",
    });
    expect(other.ok).toBe(false);
    if (other.ok) return;
    expect(isProblem(other.error, "identity-internal-tenant-exists")).toBe(true);
  });

  it("answers a persona's validation as field errors without calling identity", async () => {
    const { identity, fake } = provider();
    const result = await fake.signInAsPersona({ ...owner, roles: [], displayName: "" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("validation");
    expect(providerFailureKind(result.error)).toBe("invalid_contact");
    expect(result.error.fieldErrors).toEqual({
      displayName: ["Enter a display name."],
      roles: ["Choose at least one role."],
    });
    expect(identity.requests).toHaveLength(0);
  });

  it("takes any six digits at the code step and refuses anything else", async () => {
    const { identity, fake } = provider();
    expect((await fake.startPhoneOtp(PHONE)).ok).toBe(true);
    expect(identity.requests).toHaveLength(0);
    const bad = await fake.verifyPhoneOtp(PHONE, "12");
    expect(bad.ok).toBe(false);
    if (!bad.ok) {
      expect(providerFailureKind(bad.error)).toBe("invalid_code");
      expect(bad.error.fieldErrors).toEqual({ code: ["Enter the six digits."] });
    }
    const wrongNumber = await fake.verifyPhoneOtp("12345", "123456");
    expect(wrongNumber.ok).toBe(false);
    if (!wrongNumber.ok) expect(providerFailureKind(wrongNumber.error)).toBe("invalid_contact");
    const session = await fake.verifyPhoneOtp(PHONE, " 123 456 ");
    expect(session.ok).toBe(true);
    if (!session.ok) return;
    expect(session.value.aal).toBe("aal1");
    expect(claimsOf(session.value.accessToken)?.phone).toBe(PHONE);
    expect(session.value.expiresAt).toBe(claimsOf(session.value.accessToken)?.exp);
  });

  it("hands the email link back instead of sending it, and exchanges it", async () => {
    const { fake } = provider();
    const sent = await fake.sendEmailLink(
      "Owner@Example.test",
      "http://localhost:3000/auth/callback?next=%2Faccount",
    );
    expect(sent.ok).toBe(true);
    if (!sent.ok) return;
    const link = new URL(sent.value.devLink as string);
    expect(link.pathname).toBe("/auth/callback");
    expect(link.searchParams.get("type")).toBe("magiclink");
    expect(link.searchParams.get("next")).toBe("/account");
    const hash = link.searchParams.get("token_hash") as string;
    expect(claimsOf(hash)?.email).toBe("owner@example.test");
    const exchanged = await fake.exchangeEmailLink(hash);
    expect(exchanged.ok).toBe(true);
    if (exchanged.ok) {
      expect(decodeFakeRefreshToken(exchanged.value.refreshToken)?.contact).toEqual({
        email: "owner@example.test",
      });
    }
    const broken = await fake.exchangeEmailLink("not-a-token");
    expect(broken.ok).toBe(false);
    if (!broken.ok) expect(providerFailureKind(broken.error)).toBe("invalid_link");
    const bad = await fake.sendEmailLink("nope", "http://localhost:3000/auth/callback");
    expect(bad.ok).toBe(false);
  });

  it("refreshes from its refresh token and asserts the second factor on confirm", async () => {
    const { fake } = provider();
    const first = await fake.verifyPhoneOtp(PHONE, "000000");
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    const refreshed = await fake.refresh(first.value.refreshToken);
    expect(refreshed.ok && refreshed.value.aal).toBe("aal1");
    const challenge = await fake.mfa.challenge(first.value, FAKE_FACTOR_ID);
    expect(challenge.ok && challenge.value.challengeId).toBe(FAKE_FACTOR_ID);
    const confirmed = await fake.mfa.verify(first.value, FAKE_FACTOR_ID, FAKE_FACTOR_ID, "");
    expect(confirmed.ok).toBe(true);
    if (confirmed.ok) {
      expect(confirmed.value.aal).toBe("aal2");
      expect(claimsOf(confirmed.value.accessToken)?.aal).toBe("aal2");
    }
    const stale = await fake.refresh("fake.v1.nope");
    expect(stale.ok).toBe(false);
    if (!stale.ok) expect(providerFailureKind(stale.error)).toBe("expired");
    expect((await fake.mfa.listFactors(first.value)).ok).toBe(true);
    const enrol = await fake.mfa.enrolTotp(first.value, "x");
    expect(enrol.ok).toBe(false);
    if (!enrol.ok) expect(providerFailureKind(enrol.error)).toBe("unsupported");
    const port: AuthProvider = fake;
    await expect(port.signOut(first.value.refreshToken)).resolves.toBeUndefined();
  });

  it("says when identity does not serve the development sign-in", async () => {
    const identity = fakeIdentity();
    const fake = new FakeAuthProvider(localEnv, {
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            type: "urn:compliancewatch:problem:identity-dev-sign-in-unavailable",
            title: "Development sign-in is not served here",
            status: 404,
          }),
          { status: 404, headers: { "content-type": "application/problem+json" } },
        ),
    });
    const result = await fake.verifyPhoneOtp(PHONE, "123456");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(providerFailureKind(result.error)).toBe("unavailable");
      expect(result.error.problem?.detail).toContain("CW_AUTH_PROVIDER=fake");
    }
    expect(identity.requests).toHaveLength(0);
  });

  it("passes identity's own refusal of a persona through", async () => {
    const identity = fakeIdentity();
    const fake = new FakeAuthProvider(localEnv, {
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            type: "urn:compliancewatch:problem:identity-last-admin",
            title: "Tenant would lose its last admin",
            status: 409,
          }),
          { status: 409, headers: { "content-type": "application/problem+json" } },
        ),
    });
    const result = await fake.signInAsPersona(owner);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(isProblem(result.error, "identity-last-admin")).toBe(true);
      expect(result.error.status).toBe(409);
    }
    expect(identity.requests).toHaveLength(0);
  });
});
