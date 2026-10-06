// @vitest-environment node
import * as serverTesting from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { SCREENS, hrefFor, isCatchAll, routeParams } from "./shared/config/screens";
import { config, decide, proxy } from "./proxy";

const { unstable_doesMiddlewareMatch: doesProxyMatch, getRedirectUrl } = serverTesting;

const ORIGIN = "http://localhost:3000";

function request(path: string, cookie?: string): NextRequest {
  const headers: Record<string, string> = cookie === undefined ? {} : { cookie };
  return new NextRequest(`${ORIGIN}${path}`, { headers });
}

function exampleHref(screen: (typeof SCREENS)[number]): string {
  const params = Object.fromEntries(routeParams(screen.route).map((name) => [name, "example"]));
  return hrefFor(screen, params);
}

describe("next/experimental/testing/server", () => {
  it("still exports the matcher helper the tests below rely on", () => {
    expect(typeof doesProxyMatch).toBe("function");
    expect(typeof getRedirectUrl).toBe("function");
  });
});

describe("the matcher", () => {
  it("covers pages and skips Next assets, /api and /api-bff handlers and files", () => {
    const matches = (url: string) => doesProxyMatch({ config, url });
    expect(matches("/")).toBe(true);
    expect(matches("/admin/review/stats")).toBe(true);
    expect(matches("/sign-in?next=%2Faccount")).toBe(true);
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
    for (const path of ["/", "/sitemap", "/sign-in", "/legal/terms", "/forbidden", "/design"]) {
      expect(decide(path, "", false), path).toEqual({ kind: "pass" });
      expect(decide(path, "", true), path).toEqual({ kind: "pass" });
    }
    expect(decide("/sign-out", "", false)).toEqual({ kind: "pass" });
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

describe("proxy", () => {
  it("redirects to /sign-in with the path to return to", () => {
    const response = proxy(request("/b/1/changes?tab=2"));
    expect(response.status).toBe(307);
    expect(getRedirectUrl(response)).toBe(`${ORIGIN}/sign-in?next=%2Fb%2F1%2Fchanges%3Ftab%3D2`);
  });

  it("drops a next that is only the root and continues when a cookie exists", () => {
    expect(getRedirectUrl(proxy(request("/admin")))).toBe(`${ORIGIN}/sign-in?next=%2Fadmin`);
    const passed = proxy(request("/admin", "cw_session=anything"));
    expect(getRedirectUrl(passed)).toBeNull();
    expect(passed.headers.get("x-middleware-next")).toBe("1");
    expect(getRedirectUrl(proxy(request("/sitemap")))).toBeNull();
  });

  it("ignores other cookies", () => {
    const response = proxy(request("/businesses", "theme=dark; other=1"));
    expect(getRedirectUrl(response)).toBe(`${ORIGIN}/sign-in?next=%2Fbusinesses`);
  });
});
