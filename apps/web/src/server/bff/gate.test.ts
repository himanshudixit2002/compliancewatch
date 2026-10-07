// @vitest-environment node
import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { screenById, type Screen } from "@/shared/config/screens";
import { fakeCookies } from "@/test/fake-cookies";
import { resetEnvCache } from "../env";
import { encryptSession } from "../session";
import { gateHandler } from "./gate";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const RAW = screenById("system.raw-document");
const UPLOADS = screenById("system.uploads");
const RAW_PATH = "/api-bff/pipeline/documents/00000000-0000-4000-8000-0000000000d1/raw";
const UPLOAD_PATH = "/api-bff/pipeline/sources/example_statutes/uploads";

async function signedInAs(
  roles: SessionClaims["roles"],
  tenantKind: SessionClaims["tenantKind"] = "internal",
): Promise<void> {
  const claims: SessionClaims = {
    userId: "00000000-0000-4000-8000-0000000000a1",
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind,
    roles,
    displayName: "Example person",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function request(method: string, path: string, site = "same-origin"): Request {
  return new Request(`http://localhost:3000${path}`, {
    method,
    headers: { host: "localhost:3000", "sec-fetch-site": site },
  });
}

async function problemOf(response: Response): Promise<Record<string, unknown>> {
  expect(response.headers.get("content-type")).toContain("application/problem+json");
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  return (await response.json()) as Record<string, unknown>;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
});

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("gateHandler", () => {
  it("refuses a write from another site before it reads the session", async () => {
    await signedInAs(["admin"]);
    const gate = await gateHandler(UPLOADS, request("POST", UPLOAD_PATH, "cross-site"));
    expect(gate.ok).toBe(false);
    if (gate.ok) return;
    expect(gate.response.status).toBe(403);
    expect((await problemOf(gate.response)).type).toBe(
      "urn:compliancewatch:problem:web-cross-origin-request",
    );
    // A read is a link the browser follows from anywhere: no origin check.
    expect((await gateHandler(RAW, request("GET", RAW_PATH, "cross-site"))).ok).toBe(true);
  });

  it("sends a reader without a session to sign in and back, and refuses a writer with a 401", async () => {
    const read = await gateHandler(RAW, request("GET", RAW_PATH));
    expect(read.ok).toBe(false);
    if (read.ok) return;
    expect(read.response.status).toBe(303);
    expect(read.response.headers.get("location")).toBe(
      `/sign-in?next=${encodeURIComponent(RAW_PATH)}`,
    );
    const write = await gateHandler(UPLOADS, request("POST", UPLOAD_PATH));
    expect(write.ok).toBe(false);
    if (write.ok) return;
    expect(write.response.status).toBe(401);
    expect((await problemOf(write.response)).type).toBe(
      "urn:compliancewatch:problem:web-sign-in-required",
    );
  });

  it("hides a regulatory tool from a tenant role and names the roles to a regulatory one short of them", async () => {
    await signedInAs(["owner"], "business");
    for (const [screen, method, path] of [
      [RAW, "GET", RAW_PATH],
      [UPLOADS, "POST", UPLOAD_PATH],
    ] as const) {
      const gate = await gateHandler(screen, request(method, path));
      expect(gate.ok, screen.id).toBe(false);
      if (gate.ok) continue;
      expect(gate.response.status, screen.id).toBe(404);
      expect((await problemOf(gate.response)).type).toBe(
        "urn:compliancewatch:problem:web-not-found",
      );
    }
    await signedInAs(["analyst"]);
    const analyst = await gateHandler(UPLOADS, request("POST", UPLOAD_PATH));
    expect(analyst.ok).toBe(false);
    if (analyst.ok) return;
    expect(analyst.response.status).toBe(403);
    expect(await problemOf(analyst.response)).toMatchObject({
      type: "urn:compliancewatch:problem:web-role-required",
      title: "Your role cannot do this",
      detail: "It is for these roles only: Admin.",
    });
  });

  it("lets through a session the entry's roles and tenant kinds allow, with its claims", async () => {
    await signedInAs(["analyst"]);
    const reader = await gateHandler(RAW, request("GET", RAW_PATH));
    expect(reader.ok && reader.session.roles).toEqual(["analyst"]);
    await signedInAs(["admin"]);
    const admin = await gateHandler(UPLOADS, request("POST", UPLOAD_PATH));
    expect(admin.ok && admin.session.userId).toBe("00000000-0000-4000-8000-0000000000a1");
    const businessOnly: Screen = { ...UPLOADS, tenantKinds: ["business"] };
    const kind = await gateHandler(businessOnly, request("POST", UPLOAD_PATH));
    expect(kind.ok).toBe(false);
    if (kind.ok) return;
    expect(kind.response.status).toBe(403);
  });

  it("takes only a handler entry that names its roles", async () => {
    await expect(
      gateHandler(screenById("admin.sources"), request("GET", "/admin/sources")),
    ).rejects.toThrow(/handler entry/);
    await expect(
      gateHandler({ ...RAW, roles: "public" }, request("GET", RAW_PATH)),
    ).rejects.toThrow(/handler entry/);
  });
});
