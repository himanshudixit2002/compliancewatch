import { describe, expect, it } from "vitest";
import { planFromDto } from "@/entities/billing/mappers";
import { PLAN_DTOS } from "@/test/billing-fixture";
import { periodLabel, planView } from "./plans";

describe("planView", () => {
  it("shows the stated price in rupees with its period and the service's description", () => {
    expect(planView(planFromDto(PLAN_DTOS[0] as (typeof PLAN_DTOS)[number]))).toEqual({
      key: "example_monthly",
      name: "Example monthly plan",
      price: "Rs 1,499.00",
      period: "per month",
      description: "Example description.",
    });
    expect(planView(planFromDto(PLAN_DTOS[1] as (typeof PLAN_DTOS)[number]))).toMatchObject({
      price: "Rs 0.00",
      period: "per year",
    });
  });

  it("shows a period it has no words for as the service sends it", () => {
    expect(periodLabel("quarterly")).toBe("quarterly");
  });
});
