import { describe, expect, it } from "vitest";
import { NAV_GROUPS, adminNavFor, breadcrumbsFor, isActive, isNavGroupKey, navFor } from "./nav.ts";
import { SCREENS } from "./screens.ts";

describe("navFor", () => {
  it("gives an anonymous visitor nothing and an owner the business group once a business is known", () => {
    expect(navFor({ roles: null })).toEqual([]);
    expect(navFor({ roles: ["owner"], tenantKind: "business" }).map((s) => s.key)).toEqual([
      "settings",
      "account",
    ]);
    const withBusiness = navFor({
      roles: ["owner"],
      tenantKind: "business",
      params: { businessId: "b1" },
      currentPath: "/b/b1/calendar",
    });
    const business = withBusiness.find((section) => section.key === "business");
    expect(business?.label).toBe(NAV_GROUPS.business);
    expect(business?.items.map((item) => item.href)).toEqual([
      "/b/b1/obligations",
      "/b/b1/calendar",
      "/b/b1/changes",
      "/b/b1/reminders",
    ]);
    expect(business?.items.find((item) => item.active)?.id).toBe("owner.calendar");
  });

  it("shows a flagged screen only when its flag reads on", () => {
    const ctx = { roles: ["owner"] as const, params: { businessId: "b1" } };
    const off = navFor(ctx).flatMap((section) => section.items.map((item) => item.id));
    expect(off).not.toContain("owner.ask");
    const on = navFor({ ...ctx, isFlagEnabled: (flag) => flag === "web.qa_enabled" }).flatMap(
      (section) => section.items.map((item) => item.id),
    );
    expect(on).toContain("owner.ask");
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
