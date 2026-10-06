import { describe, expect, it } from "vitest";
import { activeHref, isActivePath, pathnameOf, safeHttpUrl, safeNext, withQuery } from "./url.ts";

describe("safeNext", () => {
  it("accepts relative paths inside the app", () => {
    expect(safeNext("/settings/team?tab=1#x")).toBe("/settings/team?tab=1#x");
    expect(safeNext("/")).toBe("/");
  });

  it("rejects other origins, protocol-relative and malformed values", () => {
    expect(safeNext("https://evil.example/")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("/a\\b")).toBe("/");
    expect(safeNext("/javascript:alert(1)")).toBe("/");
    expect(safeNext("/a b")).toBe("/");
    expect(safeNext("/a\nb")).toBe("/");
    expect(safeNext("settings")).toBe("/");
    expect(safeNext("")).toBe("/");
    expect(safeNext(null, "/home")).toBe("/home");
    expect(safeNext(undefined)).toBe("/");
  });
});

describe("withQuery and pathnameOf", () => {
  it("builds and strips query strings", () => {
    expect(withQuery("/sign-in", { next: "/settings", limit: 5, q: undefined, empty: "" })).toBe(
      "/sign-in?next=%2Fsettings&limit=5",
    );
    expect(withQuery("/sign-in", {})).toBe("/sign-in");
    expect(pathnameOf("/a/b?x=1#y")).toBe("/a/b");
    expect(pathnameOf("/a/b")).toBe("/a/b");
  });
});

describe("isActivePath", () => {
  it("marks a link active on its path and below, and section homes only on their own path", () => {
    expect(isActivePath("/settings/team", "/settings/team")).toBe(true);
    expect(isActivePath("/settings/team", "/settings/team/invite")).toBe(true);
    expect(isActivePath("/settings/team", "/settings/teams")).toBe(false);
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/", "/sitemap")).toBe(false);
    expect(isActivePath("/admin", "/admin/review")).toBe(false);
    expect(isActivePath("/b", "/b/1", [])).toBe(true);
  });
});

describe("activeHref", () => {
  it("picks the deepest active link so only one carries aria-current", () => {
    const hrefs = ["/admin", "/admin/review", "/admin/review/stats", "/admin/sources"];
    expect(activeHref(hrefs, "/admin/review/stats")).toBe("/admin/review/stats");
    expect(activeHref(hrefs, "/admin/review/t1")).toBe("/admin/review");
    expect(activeHref(hrefs, "/admin")).toBe("/admin");
    expect(activeHref(hrefs, "/settings")).toBeNull();
  });
});

describe("safeHttpUrl", () => {
  it("keeps an http or https address and drops anything else", () => {
    expect(safeHttpUrl("https://example.com/a.pdf")).toBe("https://example.com/a.pdf");
    expect(safeHttpUrl("http://example.com/")).toBe("http://example.com/");
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,x")).toBeNull();
    expect(safeHttpUrl("not a url")).toBeNull();
    expect(safeHttpUrl("")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
    expect(safeHttpUrl(undefined)).toBeNull();
  });
});
