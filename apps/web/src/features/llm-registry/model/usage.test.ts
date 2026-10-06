import { describe, expect, it } from "vitest";
import { usageFromDto } from "@/entities/llm/mappers";
import { EXAMPLE_TENANT_ID, usageDto } from "@/test/llm-fixture";
import { currentMonth, featureOptions, monthLabel, readUsage, usageRow } from "./usage";

const NOW = new Date("2000-01-31T20:00:00Z");

describe("readUsage", () => {
  it("shows every feature's budget for this month in UTC by default", () => {
    expect(readUsage({}, NOW)).toEqual({ kind: "overview", month: "2000-01" });
    expect(currentMonth(new Date("2000-02-01T00:00:00Z"))).toBe("2000-02");
  });

  it("asks for one tenant's budget, narrowed to a feature, or one feature's", () => {
    expect(
      readUsage({ tenant: EXAMPLE_TENANT_ID.toUpperCase(), feature: "qa", month: "2000-03" }, NOW),
    ).toEqual({ kind: "one", month: "2000-03", tenantId: EXAMPLE_TENANT_ID, feature: "qa" });
    expect(readUsage({ feature: "smoke" }, NOW)).toEqual({
      kind: "one",
      month: "2000-01",
      feature: "smoke",
    });
  });

  it("names each field it cannot use and reads nothing", () => {
    expect(readUsage({ tenant: "x", feature: "example", month: "2000-13" }, NOW)).toEqual({
      kind: "invalid",
      values: { tenant: "x", feature: "example", month: "2000-13" },
      errors: {
        tenant: "This is not a tenant id (a UUID).",
        feature: "Choose a feature from the list.",
        month: "Give the month as YYYY-MM, such as 2000-01.",
      },
    });
  });
});

describe("the usage wording", () => {
  it("names a month and offers every feature first", () => {
    expect(monthLabel("2000-01")).toBe("January 2000");
    expect(monthLabel("2000")).toBe("2000");
    expect(featureOptions()[0]).toEqual({ value: "", label: "Every feature" });
    expect(featureOptions().find((option) => option.value === "qa")?.label).toBe("QA");
  });

  it("shows the spend to every place the ledger keeps, and the share as a percentage", () => {
    expect(usageRow(usageFromDto(usageDto()))).toEqual({
      key: "feature:qa",
      scopeLabel: "Feature",
      keyLabel: "QA",
      spent: "Rs 1,234.0012",
      budget: "Rs 20,000.00",
      percent: "6.17%",
      barValue: 6.17,
      alarmed: false,
      resetsAt: "1 Feb 2000, 5:30 am IST",
    });
  });

  it("fills the bar for a spend over the budget and names a tenant by its id", () => {
    const row = usageRow(
      usageFromDto(
        usageDto({ scope: "tenant", key: EXAMPLE_TENANT_ID, ratio: "1.500000", alarmed: true }),
      ),
    );
    expect(row).toMatchObject({
      scopeLabel: "Tenant",
      keyLabel: EXAMPLE_TENANT_ID,
      percent: "150.00%",
      barValue: 100,
      alarmed: true,
    });
  });
});
