// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isUuid } from "@/shared/lib/identifiers";
import { EnvError, loadEnv } from "../env";
import { isProblem } from "../result";
import {
  DISPLAY_NAME_MAX_LENGTH,
  FakeAuthProvider,
  fakeUserId,
  mintFakeSession,
  uuidV5,
  validateFakeSignIn,
} from "./fake";
import type { AuthProvider, FakeSignInInput, SignInContext } from "./provider";

const NOW = new Date("2026-09-29T10:00:00Z");
const context: SignInContext = { now: NOW, ttlSeconds: 28_800 };
const TENANT = "00000000-0000-4000-8000-000000000002";

const owner: FakeSignInInput = {
  kind: "fake",
  tenantKind: "business",
  roles: ["owner"],
  displayName: "Example owner",
};

const localEnv = loadEnv({ CW_WEB_ENV: "local", CW_WEB_AUTH_PROVIDER: "fake" });

describe("uuidV5", () => {
  it("matches the RFC 4122 test vector", () => {
    const dns = "6ba7b810-9dad-11d1-80b4-00c04fd430c8";
    expect(uuidV5(dns, "www.example.com")).toBe("2ed6657d-e927-568b-95e1-2665a8aea6a2");
  });
});

describe("fakeUserId", () => {
  it("is the same user for the same name in the same tenant, whatever the case or spacing", () => {
    const id = fakeUserId(TENANT, "Example owner");
    expect(isUuid(id)).toBe(true);
    expect(fakeUserId(TENANT, "  example OWNER ")).toBe(id);
    expect(fakeUserId(TENANT, "Another name")).not.toBe(id);
    expect(fakeUserId("00000000-0000-4000-8000-000000000003", "Example owner")).not.toBe(id);
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

describe("mintFakeSession", () => {
  it("mints claims for a new tenant with the window, the fake provider and sv 1", () => {
    const result = mintFakeSession(owner, context);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const claims = result.value;
    expect(isUuid(claims.tenantId)).toBe(true);
    expect(claims).toMatchObject({
      userId: fakeUserId(claims.tenantId, "Example owner"),
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      sv: 1,
      provider: "fake",
      issuedAt: 1_790_676_000,
      expiresAt: 1_790_704_800,
    });
    expect(claims).not.toHaveProperty("cwToken");
  });

  it("keeps a given tenant, trims the name, orders and dedupes roles, and asserts mfa for the roles that need it", () => {
    const result = mintFakeSession(
      {
        kind: "fake",
        tenantId: ` ${TENANT} `,
        tenantKind: "internal",
        roles: ["admin", "analyst", "admin"],
        displayName: "  Example admin ",
      },
      context,
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tenantId).toBe(TENANT);
    expect(result.value.roles).toEqual(["analyst", "admin"]);
    expect(result.value.displayName).toBe("Example admin");
    expect(result.value.mfa).toBe(true);
    expect(result.value.userId).toBe(fakeUserId(TENANT, "Example admin"));
    const ca = mintFakeSession(
      { kind: "fake", tenantKind: "ca_firm", roles: ["ca_admin"], displayName: "CA" },
      context,
    );
    expect(ca.ok && ca.value.mfa).toBe(true);
    const staff = mintFakeSession(
      { kind: "fake", tenantKind: "business", roles: ["staff"], displayName: "Staff" },
      context,
    );
    expect(staff.ok && staff.value.mfa).toBe(false);
  });

  it("gives different tenants different users and new tenants different ids", () => {
    const first = mintFakeSession(owner, context);
    const second = mintFakeSession(owner, context);
    expect(first.ok && second.ok && first.value.tenantId !== second.value.tenantId).toBe(true);
    expect(first.ok && second.ok && first.value.userId !== second.value.userId).toBe(true);
  });

  it("answers a validation error with field errors", () => {
    const result = mintFakeSession({ ...owner, roles: [], displayName: "" }, context);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("validation");
    expect(result.error.status).toBe(422);
    expect(isProblem(result.error, "web-fake-sign-in-invalid")).toBe(true);
    expect(result.error.fieldErrors).toEqual({
      displayName: ["Enter a display name."],
      roles: ["Choose at least one role."],
    });
  });
});

describe("FakeAuthProvider", () => {
  it("is refused outside local and test", () => {
    expect(() => new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "staging" }))).toThrow(EnvError);
    expect(() => new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "prod" }))).toThrow(
      /local and test only/,
    );
    expect(new FakeAuthProvider(loadEnv({ CW_WEB_ENV: "test" })).name).toBe("fake");
  });

  it("completes a fake sign-in and refuses every other input", async () => {
    const provider: AuthProvider = new FakeAuthProvider(localEnv);
    const session = await provider.completeSignIn(owner, context);
    expect(session.ok && session.value.roles).toEqual(["owner"]);
    const otp = await provider.completeSignIn(
      { kind: "otp", challengeId: "c", code: "1" },
      context,
    );
    expect(otp.ok).toBe(false);
    if (!otp.ok) {
      expect(otp.error.kind).toBe("bad_request");
      expect(isProblem(otp.error, "web-fake-provider-input")).toBe(true);
      expect(otp.error.problem?.detail).toContain("otp");
    }
    const challenge = await provider.startSignIn({ kind: "phone", phone: "+910000000000" });
    expect(challenge.ok).toBe(false);
    if (!challenge.ok)
      expect(isProblem(challenge.error, "web-fake-provider-no-challenge")).toBe(true);
    if (session.ok) await expect(provider.signOut(session.value)).resolves.toBeUndefined();
  });
});
