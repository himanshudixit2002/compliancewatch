import { describe, expect, it } from "vitest";
import { SCREENS, screenById } from "@/shared/config/screens";
import { adminToolGroups, groupOf, toAdminTool } from "./tools";

describe("adminToolGroups", () => {
  it("lists every admin entry but the home and the catch-all, grouped like the sidebar", () => {
    const groups = adminToolGroups();
    expect(groups.map((group) => group.key)).toEqual([
      "rulebook",
      "review",
      "operations",
      "engine",
      "evals",
      "identity",
      "other",
    ]);
    const other = groups.find((group) => group.key === "other");
    expect(other?.label).toBeNull();
    expect(other?.tools.map((tool) => tool.id)).toEqual(["admin.llm.edit-controls"]);
    const ids = groups.flatMap((group) => group.tools.map((tool) => tool.id));
    const expected = SCREENS.filter(
      (s) => s.section === "admin" && s.id !== "admin.home" && !s.route.includes("[..."),
    ).map((s) => s.id);
    expect([...ids].sort()).toEqual([...expected].sort());
    expect(groups[0]?.label).toBe("Rulebook");
  });

  it("places a detail page in its parent's group after the parent", () => {
    expect(groupOf(screenById("admin.review.task"))).toBe("review");
    expect(groupOf(screenById("admin.tenant.impersonate"))).toBe("identity");
    const review = adminToolGroups().find((group) => group.key === "review");
    const ids = review?.tools.map((tool) => tool.id) ?? [];
    expect(ids.indexOf("admin.review")).toBeLessThan(ids.indexOf("admin.review.task"));
  });

  it("describes a tool with its link, roles, awaited routes and services", () => {
    const tool = toAdminTool(screenById("admin.review.task"));
    expect(tool.href).toBeNull();
    expect(tool.services).toEqual(["pipeline", "profile", "rulebook"]);
    expect(tool.waitsFor.some((item) => item.path.includes("/review/tasks/"))).toBe(true);
    expect(tool.roles).toEqual(["Analyst", "Reviewer", "Admin"]);
    const sources = toAdminTool(screenById("admin.sources"));
    expect(sources.href).toBe("/admin/sources");
    const flags = toAdminTool(screenById("admin.flags"));
    expect(flags.services).toEqual([]);
    expect(flags.waitsFor[0]?.method).toBe("file");
  });

  it("puts a tool without any placement under other", () => {
    const loose = {
      ...screenById("admin.sources"),
      id: "admin.loose",
      nav: undefined,
      parent: undefined,
    };
    const groups = adminToolGroups([loose]);
    expect(groups.map((group) => group.key)).toEqual(["other"]);
    expect(groups[0]?.label).toBeNull();
  });
});
