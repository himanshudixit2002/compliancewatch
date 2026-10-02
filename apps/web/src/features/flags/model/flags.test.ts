import { REGISTRY } from "@compliancewatch/flags";
import { describe, expect, it } from "vitest";
import { FLAG_NAMES } from "@/shared/config/flags";
import type { FlagName } from "@/shared/config/flags";
import { flagSummary, flagViews, isExpired } from "./flags";

const ALL_OFF = Object.fromEntries(FLAG_NAMES.map((name) => [name, false])) as Record<
  FlagName,
  boolean
>;

describe("flagViews", () => {
  it("lists every web flag in registry order with the registry's own wording", () => {
    const views = flagViews({ ...ALL_OFF, "web.qa_enabled": true });
    expect(views.map((view) => view.name)).toEqual([...FLAG_NAMES]);
    for (const view of views) {
      const entry = REGISTRY.get(view.name);
      expect(view.description).toBe(entry.description);
      expect(view.owner).toBe(entry.owner);
      expect(view.removal).toBe(entry.removal);
      expect(view.expires).toBe(entry.expires);
      expect(view.env).toBe(entry.env);
    }
    expect(views.filter((view) => view.enabled).map((view) => view.name)).toEqual([
      "web.qa_enabled",
    ]);
  });
});

describe("isExpired", () => {
  it("is true only once the expiry date has passed", () => {
    expect(isExpired({ expires: "2027-03-31" }, "2027-03-30")).toBe(false);
    expect(isExpired({ expires: "2027-03-31" }, "2027-03-31")).toBe(false);
    expect(isExpired({ expires: "2027-03-31" }, "2027-04-01")).toBe(true);
  });
});

describe("flagSummary", () => {
  it("counts the flags, those on and those past their expiry", () => {
    const views = flagViews({ ...ALL_OFF, "web.otel_enabled": true, "web.qa_enabled": true });
    const expired = { ...views[0]!, expires: "2020-01-01" };
    expect(flagSummary([expired, ...views.slice(1)], "2026-10-02")).toEqual({
      total: FLAG_NAMES.length,
      enabled: 2,
      expired: 1,
    });
    expect(flagSummary([], "2026-10-02")).toEqual({ total: 0, enabled: 0, expired: 0 });
  });
});
