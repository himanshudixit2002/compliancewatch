import { describe, expect, it } from "vitest";
import { screenById, type Screen } from "@/shared/config/screens";
import { businessHeaderLinks, laterScreens } from "./navigation";

const OWNER = { roles: ["owner"] as const, tenantKind: "business" as const };

describe("businessHeaderLinks", () => {
  it("names the business's crumb after the business and lists its pages", () => {
    const links = businessHeaderLinks("owner.business.attributes", OWNER, "b1", "Example business");
    expect(links.crumbs.map((crumb) => [crumb.label, crumb.href])).toEqual([
      ["Businesses", "/businesses"],
      ["Example business", "/b/b1"],
      ["Attributes", "/b/b1/attributes"],
    ]);
    expect(links.tabs[0]?.href).toBe("/b/b1");
    expect(links.tabs.map((tab) => tab.id)).toContain("owner.business.review-tasks");
    expect(links.tabs.map((tab) => tab.id)).toContain("owner.obligations");
  });

  it("lists a page behind a flag only while its flag is on", () => {
    const off = businessHeaderLinks("owner.business", OWNER, "b1", "Example business");
    expect(off.tabs.map((tab) => tab.id)).not.toContain("owner.ask");
    const on = businessHeaderLinks(
      "owner.business",
      OWNER,
      "b1",
      "Example business",
      new Set(["web.qa_enabled"] as const),
    );
    expect(on.tabs.map((tab) => tab.id)).toContain("owner.ask");
  });
});

describe("laterScreens", () => {
  it("lists the business's pages that are not built, with their notices", () => {
    // Every page of a business is built today; an example entry stands in for the next one.
    const next: Screen = {
      ...screenById("owner.changes"),
      id: "owner.example",
      route: "/b/[businessId]/example",
      status: "ready",
    };
    expect(laterScreens(OWNER, "b1")).toEqual([]);
    expect(laterScreens(OWNER, "b1", [next, screenById("owner.changes")])).toEqual([
      { id: "owner.example", title: "Changes", status: "ready", href: "/b/b1/example" },
    ]);
  });

  it("leaves out pages with more parameters and pages the viewer may not open", () => {
    const hidden: Screen = { ...screenById("owner.changes"), id: "owner.hidden", roles: ["staff"] };
    const deeper: Screen = screenById("owner.obligation");
    expect(laterScreens(OWNER, "b1", [hidden, deeper])).toEqual([]);
  });
});
