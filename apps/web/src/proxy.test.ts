// @vitest-environment node
import { randomBytes } from "node:crypto";
import * as serverTesting from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { encryptSession } from "@/server/session";
import { resetEnvCache } from "@/server/env";
import { fakeIdentity } from "@/test/identity-fixture";
import { SCREENS, hrefFor, isCatchAll, routeParams } from "./shared/config/screens";
import {
  ADMIN_NOT_FOUND_PATH,
  CSP_HEADER,
  NONCE_HEADER,
  adminGate,
  config,
  contentSecurityPolicy,
  cookieHeaderWith,
  cookieHeaderWithout,
  decide,
  makeNonce,
  proxy,
  redirectStatus,
} from "./proxy";

const {
  unstable_doesMiddlewareMatch: doesProxyMatch,
  getRedirectUrl,
  getRewrittenUrl,
  isRewrite,
} = serverTesting;

const ORIGIN = "http://localhost:3000";
const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");

function request(
  path: string,
  headers: Record<string, string> = {},
  method: "GET" | "POST" = "GET",
): NextRequest {
  return new NextRequest(`${ORIGIN}${path}`, { headers, method });
}

function exampleHref(screen: (typeof SCREENS)[number]): string {
  const params = Object.fromEntries(routeParams(screen.route).map((name) => [name, "example"]));
  return hrefFor(screen, params);
}

/** A session without an identity token: the proxy has nothing to refresh or re-read. */
async function cookieWithoutToken(): Promise<string> {
  const claims: SessionClaims = {
    userId: "00000000-0000-4000-8000-000000000001",
    tenantId: "00000000-0000-4000-8000-000000000002",
    tenantKind: "business",
    roles: ["owner"],
    displayName: "Example owner",
    mfa: false,
    sv: 0,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  return encryptSession(claims, KEY);
}

beforeEach(() => {
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  resetEnvCache();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
});

describe("next/experimental/testing/server", () => {
  it("still exports the helpers the tests below rely on", () => {
    expect(typeof doesProxyMatch).toBe("function");
    expect(typeof getRedirectUrl).toBe("function");
    expect(typeof getRewrittenUrl).toBe("function");
  });
});

describe("the matcher", () => {
  it("covers pages and skips Next assets, /api and /api-bff handlers and files", () => {
    const matches = (url: string) => doesProxyMatch({ config, url });
    expect(matches("/")).toBe(true);
    expect(matches("/admin/review/stats")).toBe(true);
    expect(matches("/sign-in?next=%2Faccount")).toBe(true);
    expect(matches("/auth/callback?token_hash=x")).toBe(true);
    expect(matches("/api-bffx")).toBe(true);
    expect(matches("/api-bff/data-requests/1/export")).toBe(false);
    expect(matches("/api-bff/pipeline/sources/example/uploads")).toBe(false);
    expect(matches("/api/health")).toBe(false);
    expect(matches("/_next/static/chunks/main.js")).toBe(false);
    expect(matches("/_next/image?url=x")).toBe(false);
    expect(matches("/icon.svg")).toBe(false);
    expect(matches("/robots.txt")).toBe(false);
  });
});

describe("decide", () => {
  it("lets public screens, handlers and unknown paths through with or without a cookie", () => {
    for (const path of [
      "/",
      "/sitemap",
      "/sign-in",
      "/sign-up",
      "/legal/terms",
      "/forbidden",
      "/design",
    ]) {
      expect(decide(path, "", false), path).toEqual({ kind: "pass" });
      expect(decide(path, "", true), path).toEqual({ kind: "pass" });
    }
    expect(decide("/sign-out", "", false)).toEqual({ kind: "pass" });
    expect(decide("/auth/callback", "", false)).toEqual({ kind: "pass" });
    expect(decide("/nowhere", "", false)).toEqual({ kind: "pass" });
    expect(decide("/b/x/nope", "", false)).toEqual({ kind: "pass" });
  });

  it("sends an anonymous visitor to sign-in from role-gated screens and from /admin", () => {
    expect(decide("/businesses", "", false)).toEqual({ kind: "sign-in", next: "/businesses" });
    expect(decide("/account/mfa", "", false)).toEqual({ kind: "sign-in", next: "/account/mfa" });
    expect(decide("/b/1/changes", "?tab=2", false)).toEqual({
      kind: "sign-in",
      next: "/b/1/changes?tab=2",
    });
    expect(decide("/admin", "", false)).toEqual({ kind: "sign-in", next: "/admin" });
    expect(decide("/admin/nowhere", "", false)).toEqual({
      kind: "sign-in",
      next: "/admin/nowhere",
    });
    expect(decide("/administration", "", false)).toEqual({ kind: "pass" });
  });

  it("passes every gated screen once a cookie is present", () => {
    expect(decide("/businesses", "", true)).toEqual({ kind: "pass" });
    expect(decide("/admin/review", "", true)).toEqual({ kind: "pass" });
  });

  it("lets a pending sign-in reach the two-step verification page and nothing else", () => {
    expect(decide("/account/mfa", "?next=%2Fadmin", false, true)).toEqual({ kind: "pass" });
    expect(decide("/account", "", false, true)).toEqual({ kind: "sign-in", next: "/account" });
    expect(decide("/admin", "", false, true)).toEqual({ kind: "sign-in", next: "/admin" });
  });

  it("agrees with the registry for every page", () => {
    const pages = SCREENS.filter((screen) => screen.kind === "page" && !isCatchAll(screen.route));
    for (const screen of pages) {
      const href = exampleHref(screen);
      const anonymous = decide(href, "", false).kind;
      const gated = screen.roles !== "public" || screen.section === "admin";
      expect(anonymous, screen.id).toBe(gated ? "sign-in" : "pass");
      expect(decide(href, "", true).kind, screen.id).toBe("pass");
    }
  });
});

describe("adminGate", () => {
  it("opens an empty list outside prod and closes it in prod", () => {
    expect(adminGate("203.0.113.9", [], "local")).toBe("allowed");
    expect(adminGate(null, [], "test")).toBe("allowed");
    expect(adminGate(null, [], "staging")).toBe("allowed");
    expect(adminGate("203.0.113.9", [], "prod")).toBe("not-found");
    expect(adminGate(null, [], "prod")).toBe("not-found");
  });

  it("admits the listed ranges and refuses everything else, an unknown address included", () => {
    const list = ["10.0.0.0/8", "2001:db8::/32"];
    expect(adminGate("10.1.2.3", list, "prod")).toBe("allowed");
    expect(adminGate("2001:db8::7", list, "local")).toBe("allowed");
    expect(adminGate("203.0.113.9", list, "prod")).toBe("forbidden");
    expect(adminGate("203.0.113.9", list, "local")).toBe("forbidden");
    expect(adminGate(null, list, "local")).toBe("forbidden");
    expect(adminGate("10.1.2.3", ["junk"], "local")).toBe("allowed");
  });
});

describe("contentSecurityPolicy", () => {
  it("names the nonce for scripts, allows inline styles, and relaxes only for next dev", () => {
    const nonce = makeNonce();
    expect(Buffer.from(nonce, "base64").toString()).toMatch(/^[0-9a-f-]{36}$/);
    const prod = contentSecurityPolicy(nonce, { dev: false, secure: true });
    expect(prod).toContain(`script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`);
    expect(prod).toContain("style-src 'self' 'unsafe-inline'");
    expect(prod).toContain("frame-ancestors 'none'");
    expect(prod).toContain("form-action 'self'");
    expect(prod).toContain("upgrade-insecure-requests");
    expect(prod).not.toContain("unsafe-eval");
    const dev = contentSecurityPolicy(nonce, { dev: true, secure: false });
    expect(dev).toContain("'unsafe-eval'");
    expect(dev).toContain("connect-src 'self' ws: wss:");
    expect(dev).not.toContain("upgrade-insecure-requests");
  });
});

describe("cookie header helpers", () => {
  it("replace, add and drop one cookie, keeping the others", () => {
    const withBoth = request("/", { cookie: "theme=dark; cw_session=old" });
    expect(cookieHeaderWith(withBoth, "cw_session", "new")).toBe("theme=dark; cw_session=new");
    expect(cookieHeaderWithout(withBoth, "cw_session")).toBe("theme=dark");
    expect(cookieHeaderWith(request("/"), "cw_session", "new")).toBe("cw_session=new");
    expect(cookieHeaderWithout(request("/", { cookie: "cw_session=old" }), "cw_session")).toBe("");
  });
});

describe("proxy", () => {
  it("redirects to /sign-in with the path to return to, and sets the policy on every answer", async () => {
    const response = await proxy(request("/b/1/changes?tab=2"));
    expect(response.status).toBe(307);
    expect(getRedirectUrl(response)).toBe(`${ORIGIN}/sign-in?next=%2Fb%2F1%2Fchanges%3Ftab%3D2`);
    expect(response.headers.get(CSP_HEADER)).toContain("nonce-");
  });

  it("answers a posted request with a 303, so the browser does not replay the body", async () => {
    expect(redirectStatus("GET")).toBe(307);
    expect(redirectStatus("HEAD")).toBe(307);
    expect(redirectStatus("POST")).toBe(303);
    const posted = await proxy(request("/settings/team", {}, "POST"));
    expect(posted.status).toBe(303);
    expect(getRedirectUrl(posted)).toBe(`${ORIGIN}/sign-in?next=%2Fsettings%2Fteam`);
  });

  it("signs a revoked session out: 303 for an action's POST, the cookie cleared", async () => {
    const identity = fakeIdentity();
    vi.stubGlobal("fetch", identity.fetchImpl);
    const user = identity.provision({
      contact: { phone: "+919876543210" },
      kind: "business",
      roles: ["owner"],
    });
    const claims: SessionClaims = {
      userId: user.id,
      tenantId: user.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      sv: 0,
      provider: "fake",
      ...sessionWindow(new Date(), 3600),
      cwToken: identity.accessToken(user),
      cwTokenExpiresAt: Math.floor(Date.now() / 1000) + 500,
      checkedAt: 0,
    };
    identity.bump(user.id, { disabled: true });
    const cookie = `cw_session=${await encryptSession(claims, KEY)}`;
    const posted = await proxy(request("/settings/team", { cookie }, "POST"));
    expect(posted.status).toBe(303);
    expect(getRedirectUrl(posted)).toBe(`${ORIGIN}/sign-in?reason=signed-out`);
    expect(posted.headers.get("set-cookie")).toMatch(/^cw_session=;.*Max-Age=0/i);
    const page = await proxy(request("/settings/team", { cookie }));
    expect(page.status).toBe(307);
    expect(getRedirectUrl(page)).toBe(`${ORIGIN}/sign-in?reason=signed-out`);
  });

  it("drops a next that is only the root and continues when a cookie exists", async () => {
    expect(getRedirectUrl(await proxy(request("/admin")))).toBe(`${ORIGIN}/sign-in?next=%2Fadmin`);
    const passed = await proxy(request("/admin", { cookie: "cw_session=anything" }));
    expect(getRedirectUrl(passed)).toBeNull();
    expect(passed.headers.get("x-middleware-next")).toBe("1");
    expect(getRedirectUrl(await proxy(request("/sitemap")))).toBeNull();
  });

  it("ignores other cookies", async () => {
    const response = await proxy(request("/businesses", { cookie: "theme=dark; other=1" }));
    expect(getRedirectUrl(response)).toBe(`${ORIGIN}/sign-in?next=%2Fbusinesses`);
  });

  it("forwards the nonce and the policy to the render", async () => {
    const response = await proxy(request("/sitemap"));
    const nonce = response.headers.get("x-middleware-request-x-nonce");
    expect(nonce).not.toBeNull();
    expect(response.headers.get(`x-middleware-request-${CSP_HEADER}`)).toContain(
      `'nonce-${nonce}'`,
    );
    expect(response.headers.get(CSP_HEADER)).toContain(`'nonce-${nonce}'`);
    expect(response.headers.get("x-middleware-override-headers")).toContain(NONCE_HEADER);
  });

  it("clears a cookie on the way to the sign-in page that says the session ended", async () => {
    const response = await proxy(
      request("/sign-in?reason=signed-out", { cookie: "theme=dark; cw_session=stale" }),
    );
    expect(getRedirectUrl(response)).toBeNull();
    expect(response.headers.get("set-cookie")).toMatch(/^cw_session=;.*Max-Age=0/i);
    expect(response.headers.get("x-middleware-request-cookie")).toBe("theme=dark");
    const plain = await proxy(request("/sign-in?reason=signed-out"));
    expect(plain.headers.get("set-cookie")).toBeNull();
  });

  it("applies the /admin allow-list from trusted headers only", async () => {
    vi.stubEnv("CW_WEB_ADMIN_IP_ALLOWLIST", "10.0.0.0/8");
    vi.stubEnv("CW_WEB_TRUST_FORWARDED_IP", "true");
    resetEnvCache();
    const cookie = `cw_session=${await cookieWithoutToken()}`;
    const inside = await proxy(
      request("/admin/review", { cookie, "x-forwarded-for": "10.2.3.4, 203.0.113.1" }),
    );
    expect(isRewrite(inside)).toBe(false);
    expect(getRedirectUrl(inside)).toBeNull();
    const outside = await proxy(request("/admin/review", { cookie, "x-real-ip": "203.0.113.9" }));
    expect(isRewrite(outside)).toBe(true);
    expect(getRewrittenUrl(outside)).toBe(`${ORIGIN}/forbidden`);
    const unknown = await proxy(request("/admin", { cookie }));
    expect(getRewrittenUrl(unknown)).toBe(`${ORIGIN}/forbidden`);
    vi.stubEnv("CW_WEB_TRUST_FORWARDED_IP", "false");
    resetEnvCache();
    const untrusted = await proxy(request("/admin", { cookie, "x-real-ip": "10.2.3.4" }));
    expect(getRewrittenUrl(untrusted)).toBe(`${ORIGIN}/forbidden`);
    const elsewhere = await proxy(request("/businesses", { cookie, "x-real-ip": "203.0.113.9" }));
    expect(isRewrite(elsewhere)).toBe(false);
  });

  it("answers 404 for /admin in prod with an empty list, and opens it elsewhere", async () => {
    vi.stubEnv("CW_WEB_ENV", "prod");
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "supabase");
    vi.stubEnv("CW_WEB_SUPABASE_URL", "https://project.supabase.test");
    vi.stubEnv("CW_WEB_SUPABASE_ANON_KEY", "anon");
    vi.stubEnv("CW_WEB_PUBLIC_URL", "https://app.example.test");
    resetEnvCache();
    const cookie = `cw_session=${await cookieWithoutToken()}`;
    const closed = await proxy(request("/admin/review", { cookie }));
    expect(getRewrittenUrl(closed)).toBe(`${ORIGIN}${ADMIN_NOT_FOUND_PATH}`);
    vi.stubEnv("CW_WEB_ENV", "staging");
    resetEnvCache();
    const open = await proxy(request("/admin/review", { cookie }));
    expect(isRewrite(open)).toBe(false);
  });

  it("leaves a session without an identity token alone", async () => {
    const cookie = `cw_session=${await cookieWithoutToken()}`;
    const response = await proxy(request("/account", { cookie }));
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(getRedirectUrl(response)).toBeNull();
  });
});
