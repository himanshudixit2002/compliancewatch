import { describe, expect, it } from "vitest";
import { homeLinks, homeSectionsFor } from "./links";

describe("homeLinks", () => {
  it("points at sign-in, the sitemap, the internal tools and the three legal drafts", () => {
    const links = homeLinks();
    expect(links.signIn).toBe("/sign-in");
    expect(links.sitemap).toBe("/sitemap");
    expect(links.admin).toBe("/admin");
    expect(links.legal.map((link) => link.href)).toEqual([
      "/legal/privacy-notice",
      "/legal/terms-of-service",
      "/legal/whatsapp-consent",
    ]);
    expect(links.legal[0]?.label).toBe("Privacy notice");
  });
});

describe("homeSectionsFor", () => {
  it("gives an anonymous visitor nothing", () => {
    expect(homeSectionsFor({ roles: null })).toEqual([]);
  });

  it("lists the sections an owner may open with each screen's status", () => {
    const sections = homeSectionsFor({
      roles: ["owner"],
      tenantKind: "business",
      params: { businessId: "b1" },
    });
    const business = sections.find((section) => section.key === "business");
    expect(business?.label).toBe("Your business");
    const changes = business?.items.find((item) => item.id === "owner.changes");
    expect(changes).toEqual({
      id: "owner.changes",
      title: "Changes",
      href: "/b/b1/changes",
      status: "ready",
    });
  });
});
