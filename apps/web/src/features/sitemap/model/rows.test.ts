import { describe, expect, it } from "vitest";
import { SCREENS, screenById } from "@/shared/config/screens";
import { SECTION_ORDER, countRows, sitemapSections, toSitemapRow } from "./rows";

describe("sitemapSections", () => {
  it("groups every non-catch-all entry by section in display order", () => {
    const sections = sitemapSections();
    expect(sections.map((section) => section.key)).toEqual(SECTION_ORDER);
    const ids = sections.flatMap((section) => section.rows.map((row) => row.id));
    expect(ids).not.toContain("system.not-available");
    expect(ids).not.toContain("admin.not-available");
    expect(countRows(sections)).toBe(SCREENS.filter((s) => !s.route.includes("[...")).length);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("links static pages, leaves parameterised and non-page routes as text", () => {
    expect(toSitemapRow(screenById("system.sitemap")).href).toBe("/sitemap");
    expect(toSitemapRow(screenById("admin.review")).href).toBe("/admin/review");
    expect(toSitemapRow(screenById("owner.obligations")).href).toBeNull();
    expect(toSitemapRow(screenById("system.health")).href).toBeNull();
    expect(toSitemapRow(screenById("owner.report-error")).kind).toBe("component");
  });

  it("expands the legal route into one link per document and lists awaited routes", () => {
    const legal = toSitemapRow(screenById("system.legal"));
    expect(legal.href).toBeNull();
    expect(legal.links.map((link) => link.href)).toEqual([
      "/legal/privacy-notice",
      "/legal/terms-of-service",
      "/legal/whatsapp-consent",
    ]);
    const ask = toSitemapRow(screenById("owner.ask"));
    expect(ask.waitsFor).toEqual([{ method: "POST", path: "/v1/qa/ask", owner: "KAG track" }]);
    expect(ask.roles).toContain("Owner");
    const flags = toSitemapRow(screenById("admin.flags"));
    expect(flags.waitsFor[0]?.method).toBe("file");
  });

  it("drops empty sections", () => {
    expect(sitemapSections([screenById("system.home")]).map((s) => s.key)).toEqual(["system"]);
  });
});
