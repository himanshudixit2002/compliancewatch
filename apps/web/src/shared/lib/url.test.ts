import { describe, expect, it } from "vitest";
import { pathnameOf, safeNext, withQuery } from "./url.ts";

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
