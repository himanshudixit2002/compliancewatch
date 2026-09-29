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
  });
});

describe("laterScreens", () => {
  it("lists the business's pages that are not built, with their notices", () => {
    const later = laterScreens(OWNER, "b1");
    expect(later.map((screen) => screen.id)).toEqual(["owner.changes", "owner.reminders"]);
    expect(later[0]).toMatchObject({ status: "waiting", href: "/b/b1/changes" });
  });

  it("leaves out pages with more parameters and pages the viewer may not open", () => {
    const hidden: Screen = { ...screenById("owner.changes"), id: "owner.hidden", roles: ["staff"] };
    const deeper: Screen = screenById("owner.obligation");
    expect(laterScreens(OWNER, "b1", [hidden, deeper])).toEqual([]);
  });
});
