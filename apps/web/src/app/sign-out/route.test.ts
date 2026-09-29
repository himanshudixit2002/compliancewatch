// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

/** A POST as `next start` sees it: the URL carries the bind address, the headers the browser's host. */
function signOut(sent: Record<string, string>): Promise<Response> | Response {
  return POST(new NextRequest("http://localhost:3000/sign-out", { method: "POST", headers: sent }));
}

describe("POST /sign-out", () => {
  it("signs out a page served under another host name and stays on that host", async () => {
    const response = await signOut({
      host: "app.example.com",
      origin: "http://app.example.com",
      cookie: "cw_session=abc",
    });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/sign-in");
    expect(response.headers.get("set-cookie")).toMatch(/^cw_session=;/);
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
    const cookies = response.headers.getSetCookie();
    expect(cookies).toHaveLength(2);
    expect(cookies[1]).toMatch(/^cw_prefs_recipient=;/);
    expect(cookies[1]).toMatch(/Path=\/settings/);
    expect(cookies[1]).toMatch(/Max-Age=0/i);
  });

  it("accepts a browser's same-origin form post on a loopback address", async () => {
    const response = await signOut({ host: "127.0.0.1:3291", "sec-fetch-site": "same-origin" });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/sign-in");
  });

  it("keeps a relative redirect when a proxy says the scheme was https", async () => {
    const response = await signOut({ host: "localhost:3000", "x-forwarded-proto": "https" });
    expect(response.headers.get("location")).toBe("/sign-in");
  });

  it("refuses another site with a problem and leaves the cookie alone", async () => {
    const response = await signOut({ host: "app.example.com", origin: "https://evil.example" });
    expect(response.status).toBe(403);
    expect(response.headers.get("content-type")).toContain("application/problem+json");
    expect(await response.json()).toMatchObject({
      type: "urn:compliancewatch:problem:web-cross-origin-request",
      status: 403,
    });
    expect(response.headers.get("set-cookie")).toBeNull();
    const crossSite = await signOut({ host: "app.example.com", "sec-fetch-site": "cross-site" });
    expect(crossSite.status).toBe(403);
  });

  it("reads the forwarded host only when the deployment trusts its proxy", async () => {
    const proxied = {
      host: "10.0.0.5:3000",
      origin: "https://app.example.com",
      "x-forwarded-host": "app.example.com",
    };
    expect((await signOut(proxied)).status).toBe(403);
    vi.stubEnv("CW_WEB_TRUST_FORWARDED_IP", "true");
    resetEnvCache();
    expect((await signOut(proxied)).status).toBe(303);
  });
});
