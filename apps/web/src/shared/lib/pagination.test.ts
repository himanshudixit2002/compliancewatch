import { describe, expect, it } from "vitest";
import { firstPageHref, nextPageHref, pageQueryString, parsePageQuery } from "./pagination.ts";

describe("pagination", () => {
  it("reads and clamps the page query", () => {
    expect(parsePageQuery({})).toEqual({ limit: 20 });
    expect(parsePageQuery({ limit: "50", after: "abc" })).toEqual({ limit: 50, after: "abc" });
    expect(parsePageQuery({ limit: "500" })).toEqual({ limit: 100 });
    expect(parsePageQuery({ limit: "-1" })).toEqual({ limit: 20 });
    expect(parsePageQuery({ limit: "x", after: "" })).toEqual({ limit: 20 });
    expect(parsePageQuery({ limit: ["10", "20"] })).toEqual({ limit: 10 });
    expect(parsePageQuery(new URLSearchParams("limit=5&after=c1"))).toEqual({
      limit: 5,
      after: "c1",
    });
    expect(parsePageQuery(new URLSearchParams(""), { defaultLimit: 10, maxLimit: 10 })).toEqual({
      limit: 10,
    });
  });

  it("builds query strings that keep filters and drop defaults", () => {
    expect(pageQueryString({ limit: 20 })).toBe("");
    expect(pageQueryString({ limit: 50, after: "c1" }, { status: "open", q: "" })).toBe(
      "?status=open&limit=50&after=c1",
    );
  });

  it("links to the next page only when a cursor came back", () => {
    expect(nextPageHref("/admin/sources", { limit: 20 }, "c2")).toBe("/admin/sources?after=c2");
    expect(nextPageHref("/admin/sources", { limit: 20, after: "c1" }, null)).toBeNull();
    expect(nextPageHref("/admin/sources", { limit: 20 }, "")).toBeNull();
    expect(firstPageHref("/admin/sources", { limit: 50, after: "c9" }, { status: "open" })).toBe(
      "/admin/sources?status=open&limit=50",
    );
  });
});
