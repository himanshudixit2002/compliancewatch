import { describe, expect, it } from "vitest";
import {
  NAV_GROUPS,
  adminNavFor,
  breadcrumbsFor,
  forbiddenHref,
  homeFor,
  isActive,
  isNavGroupKey,
  navFor,
  publicNav,
  signInHref,
} from "./nav.ts";
import { SCREENS, screenById } from "./screens.ts";
import type { Screen } from "./screens.ts";

describe("publicNav", () => {
  it("links the home page and the sitemap for every visitor and marks the current one", () => {
    expect(publicNav().map((link) => link.href)).toEqual(["/", "/sitemap"]);
    expect(publicNav().some((link) => link.active)).toBe(false);
    expect(publicNav("/sitemap").find((link) => link.active)?.id).toBe("system.sitemap");
  });
});

describe("navFor", () => {
  it("gives an anonymous visitor nothing and an owner the business links a business is known for", () => {
    expect(navFor({ roles: null })).toEqual([]);
    const withoutBusiness = navFor({ roles: ["owner"], tenantKind: "business" });
    expect(withoutBusiness.map((s) => s.key)).toEqual(["business", "settings", "account"]);
    expect(withoutBusiness[0]?.items.map((item) => item.href)).toEqual(["/businesses"]);
    const withBusiness = navFor({
      roles: ["owner"],
      tenantKind: "business",
      params: { businessId: "b1" },
      currentPath: "/b/b1/changes",
    });
    const business = withBusiness.find((section) => section.key === "business");
    expect(business?.label).toBe(NAV_GROUPS.business);
    expect(business?.items.map((item) => item.href)).toEqual([
      "/businesses",
      "/b/b1/changes",
      "/b/b1/reminders",
    ]);
    expect(business?.items.find((item) => item.active)?.id).toBe("owner.changes");
  });

  it("shows a flagged screen only when its flag reads on", () => {
    const flagged: Screen = {
      ...screenById("owner.changes"),
      id: "owner.flagged",
      route: "/b/[businessId]/flagged",
      flag: "web.qa_enabled",
    };
    const screens = [...SCREENS, flagged];
    const ctx = { roles: ["owner"] as const, params: { businessId: "b1" } };
    const off = navFor(ctx, screens).flatMap((section) => section.items.map((item) => item.id));
    expect(off).not.toContain("owner.flagged");
    const on = navFor(
      { ...ctx, isFlagEnabled: (flag) => flag === "web.qa_enabled" },
      screens,
    ).flatMap((section) => section.items.map((item) => item.id));
    expect(on).toContain("owner.flagged");
  });

  it("filters by role and tenant kind", () => {
    const staff = navFor({ roles: ["staff"], tenantKind: "business" }).flatMap((s) =>
      s.items.map((i) => i.id),
    );
    expect(staff).not.toContain("owner.settings.team");
    const ca = navFor({ roles: ["ca_admin"], tenantKind: "ca_firm" }).flatMap((s) =>
      s.items.map((i) => i.id),
    );
    expect(ca).toContain("ca.clients");
    expect(ca).toContain("ca.settings.webhooks");
    expect(ca).not.toContain("owner.evidence");
    expect(adminNavFor({ roles: ["owner"] })).toEqual([]);
  });

  it("groups the admin tools and orders them", () => {
    const sections = adminNavFor({
      roles: ["admin"],
      tenantKind: "internal",
      currentPath: "/admin/sources/cbic",
    });
    expect(sections.map((s) => s.key)).toEqual([
      "rulebook",
      "review",
      "operations",
      "engine",
      "evals",
      "identity",
    ]);
    const operations = sections.find((s) => s.key === "operations");
    expect(operations?.items[0]?.id).toBe("admin.sources");
    expect(operations?.items[0]?.active).toBe(true);
    const analyst = adminNavFor({ roles: ["analyst"], tenantKind: "internal" });
    expect(analyst.find((s) => s.key === "identity")).toBeUndefined();
  });

  it("only uses known group keys on registry entries", () => {
    for (const screen of SCREENS) {
      if (screen.nav) expect(isNavGroupKey(screen.nav.group), screen.id).toBe(true);
    }
    expect(isNavGroupKey("nope")).toBe(false);
  });
});

describe("isActive", () => {
  it("matches the path and its children, except for the home links", () => {
    expect(isActive("/admin/sources", "/admin/sources/cbic")).toBe(true);
    expect(isActive("/admin/sources", "/admin/sourcesx")).toBe(false);
    expect(isActive("/admin", "/admin/sources")).toBe(false);
    expect(isActive("/", "/")).toBe(true);
  });
});

describe("breadcrumbsFor", () => {
  it("walks the parent chain root first with filled hrefs", () => {
    expect(breadcrumbsFor("admin.review.task", { taskId: "t1" })).toEqual([
      { id: "admin.home", href: "/admin", label: "Internal tools" },
      { id: "admin.review", href: "/admin/review", label: "Review queue" },
      { id: "admin.review.task", href: "/admin/review/t1", label: "Review workbench" },
    ]);
    expect(breadcrumbsFor("system.home")).toEqual([
      { id: "system.home", href: "/", label: "Home" },
    ]);
  });
});

describe("homeFor", () => {
  it("sends regulatory roles to the internal tools and every tenant role to the businesses", () => {
    expect(homeFor({ roles: ["analyst"], tenantKind: "internal" })).toBe("/admin");
    expect(homeFor({ roles: ["reviewer", "admin"] })).toBe("/admin");
    expect(homeFor({ roles: ["owner"], tenantKind: "business" })).toBe("/businesses");
    expect(homeFor({ roles: ["ca_staff"], tenantKind: "ca_firm" })).toBe("/businesses");
    expect(homeFor({ roles: ["compliance_lead"] })).toBe("/businesses");
  });
});

describe("signInHref and forbiddenHref", () => {
  it("carry a same-origin next and drop the root, the sign-in page and foreign URLs", () => {
    expect(signInHref()).toBe("/sign-in");
    expect(signInHref("/")).toBe("/sign-in");
    expect(signInHref("/sign-in")).toBe("/sign-in");
    expect(signInHref("/sign-in?next=%2Faccount")).toBe("/sign-in");
    expect(signInHref("/account")).toBe("/sign-in?next=%2Faccount");
    expect(signInHref("/b/1/changes?tab=2")).toBe("/sign-in?next=%2Fb%2F1%2Fchanges%3Ftab%3D2");
    expect(signInHref("https://evil.example/")).toBe("/sign-in");
    expect(signInHref("//evil.example")).toBe("/sign-in");
    expect(forbiddenHref()).toBe("/forbidden");
  });
});
