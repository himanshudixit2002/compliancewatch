// @vitest-environment node
import { randomBytes } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { screenById } from "@/shared/config/screens";
import { fakeCookies } from "@/test/fake-cookies";
import {
  requireAdmin,
  requireRole,
  requireScreen,
  requireScreenSession,
  requireSession,
  requireTenantKind,
  sessionForRender,
  verifySession,
} from "./dal";
import { EnvError, resetEnvCache } from "./env";
import { encryptSession } from "./session";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

class NotFoundSignal extends Error {}

function claimsFor(overrides: Partial<SessionClaims>): SessionClaims {
  return {
    userId: "00000000-0000-4000-8000-000000000001",
    tenantId: "00000000-0000-4000-8000-000000000002",
    tenantKind: "business",
    roles: ["owner"],
    displayName: "Example owner",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
}

async function signedInAs(overrides: Partial<SessionClaims>): Promise<SessionClaims> {
  const claims = claimsFor(overrides);
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
  return claims;
}

const redirectsTo = async (promise: Promise<unknown>, href: string) => {
  await expect(promise).rejects.toThrow(Redirected);
  await expect(promise).rejects.toMatchObject({ href });
};

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new NotFoundSignal("not found");
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
});

describe("verifySession", () => {
  it("answers null without a cookie, with an empty one and with a bad one", async () => {
    expect(await verifySession()).toBeNull();
    fakeCookies.set("cw_session", "");
    expect(await verifySession()).toBeNull();
    fakeCookies.set("cw_session", "not-a-session");
    expect(await verifySession()).toBeNull();
  });

  it("decrypts a cookie under the configured secret", async () => {
    const claims = await signedInAs({ roles: ["analyst"], tenantKind: "internal" });
    expect(await verifySession()).toEqual(claims);
  });

  it("refuses to run with a cookie and no secret", async () => {
    await signedInAs({});
    vi.unstubAllEnvs();
    resetEnvCache();
    await expect(verifySession()).rejects.toThrow(EnvError);
  });
});

describe("requireSession", () => {
  it("returns the claims, or redirects to sign-in with a safe next", async () => {
    await redirectsTo(requireSession(), "/sign-in");
    await redirectsTo(requireSession({ next: "/account" }), "/sign-in?next=%2Faccount");
    await redirectsTo(requireSession({ next: "https://evil.example/" }), "/sign-in");
    const claims = await signedInAs({});
    expect(await requireSession()).toEqual(claims);
  });
});

describe("requireRole", () => {
  it("lets a public gate through anonymous or signed in", async () => {
    expect(await requireRole("public")).toBeNull();
    const claims = await signedInAs({});
    expect(await requireRole("public")).toEqual(claims);
  });

  it("sends anonymous visitors to sign-in and the wrong role to /forbidden", async () => {
    await redirectsTo(
      requireRole(["owner"], { next: "/businesses" }),
      "/sign-in?next=%2Fbusinesses",
    );
    await signedInAs({ roles: ["staff"] });
    await redirectsTo(requireRole(["owner", "ca_admin"]), "/forbidden");
    expect(await requireRole(["staff", "owner"])).toMatchObject({ roles: ["staff"] });
  });
});

describe("requireTenantKind", () => {
  it("checks the session's tenant kind", async () => {
    await redirectsTo(requireTenantKind(["ca_firm"]), "/sign-in");
    await signedInAs({ tenantKind: "business" });
    await redirectsTo(requireTenantKind(["ca_firm"]), "/forbidden");
    expect(await requireTenantKind(["business", "ca_firm"])).toMatchObject({
      tenantKind: "business",
    });
  });
});

describe("requireAdmin", () => {
  it("answers 404 for a tenant role and sign-in for nobody", async () => {
    await redirectsTo(requireAdmin({ next: "/admin" }), "/sign-in?next=%2Fadmin");
    await signedInAs({ roles: ["owner"] });
    await expect(requireAdmin()).rejects.toThrow(NotFoundSignal);
    expect(vi.mocked(redirect)).toHaveBeenCalledTimes(1);
    for (const role of ["analyst", "reviewer", "admin"] as const) {
      await signedInAs({ roles: [role], tenantKind: "internal" });
      expect(await requireAdmin()).toMatchObject({ roles: [role] });
    }
  });
});

describe("requireScreen", () => {
  it("applies the entry's roles, tenant kinds and section", async () => {
    const businesses = screenById("owner.businesses");
    await redirectsTo(requireScreen(businesses), "/sign-in?next=%2Fbusinesses");
    await signedInAs({ roles: ["analyst"], tenantKind: "internal" });
    await redirectsTo(requireScreen(businesses), "/forbidden");
    await signedInAs({ roles: ["owner"], tenantKind: "business" });
    expect(await requireScreen(businesses)).toMatchObject({ roles: ["owner"] });

    const clients = screenById("ca.clients");
    await signedInAs({ roles: ["ca_admin"], tenantKind: "business" });
    await redirectsTo(requireScreen(clients), "/forbidden");

    const obligation = screenById("owner.obligation");
    await signedInAs({ roles: ["owner"], tenantKind: "business" });
    expect(await requireScreen(obligation, { businessId: "b", obligationId: "o" })).toMatchObject({
      roles: ["owner"],
    });
    fakeCookies.reset();
    await redirectsTo(
      requireScreen(obligation, { businessId: "b", obligationId: "o" }),
      "/sign-in?next=%2Fb%2Fb%2Fobligations%2Fo",
    );

    const home = screenById("system.home");
    expect(await requireScreen(home)).toBeNull();

    const review = screenById("admin.review");
    await redirectsTo(requireScreen(review), "/sign-in?next=%2Fadmin%2Freview");
    await signedInAs({ roles: ["owner"], tenantKind: "business" });
    await expect(requireScreen(review)).rejects.toThrow(NotFoundSignal);
    await signedInAs({ roles: ["reviewer"], tenantKind: "internal" });
    expect(await requireScreen(review)).toMatchObject({ roles: ["reviewer"] });

    const team = screenById("admin.team");
    await signedInAs({ roles: ["analyst"], tenantKind: "internal" });
    await expect(requireScreen(team)).rejects.toThrow(NotFoundSignal);
    await signedInAs({ roles: ["admin"], tenantKind: "internal" });
    expect(await requireScreen(team)).toMatchObject({ roles: ["admin"] });
  });
});

describe("requireScreenSession", () => {
  it("returns the claims for a gated entry and refuses a public one", async () => {
    const account = screenById("account.home");
    await redirectsTo(requireScreenSession(account), "/sign-in?next=%2Faccount");
    await signedInAs({ roles: ["staff"], tenantKind: "business" });
    expect(await requireScreenSession(account)).toMatchObject({ roles: ["staff"] });
    await expect(requireScreenSession(screenById("system.home"))).rejects.toThrow(/is public/);
  });
});

describe("sessionForRender", () => {
  it("returns the render-safe facts or null", async () => {
    expect(await sessionForRender()).toBeNull();
    await signedInAs({ cwToken: "service-token", displayName: "Example owner" });
    const dto = await sessionForRender();
    expect(dto).toMatchObject({ displayName: "Example owner", roles: ["owner"] });
    expect(dto).not.toHaveProperty("cwToken");
  });
});
