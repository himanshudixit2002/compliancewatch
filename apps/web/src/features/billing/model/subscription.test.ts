import { describe, expect, it } from "vitest";
import { planFromDto, subscriptionFromDto } from "@/entities/billing/mappers";
import { PLAN_DTOS, subscriptionDto } from "@/test/billing-fixture";
import { statusLabel, subscriptionView } from "./subscription";

const PLANS = PLAN_DTOS.map(planFromDto);

describe("subscriptionView", () => {
  it("names the plan, the status and the start in IST, with the checkout page", () => {
    expect(subscriptionView(subscriptionFromDto(subscriptionDto()), PLANS)).toEqual({
      planName: "Example monthly plan",
      status: "Created",
      providerSubscriptionId: "sub_example_1",
      startedAt: "1 Jan 2000, 5:30 am IST",
      checkoutUrl: "https://checkout.example.com/sub_example_1",
    });
  });

  it("offers no link for an empty or a non-web checkout address, and keeps an unknown plan's key", () => {
    const empty = subscriptionView(
      subscriptionFromDto(subscriptionDto({ checkout_url: "", plan_key: "other_plan" })),
      PLANS,
    );
    expect(empty).toMatchObject({ checkoutUrl: null, planName: "other_plan" });
    const script = subscriptionView(
      subscriptionFromDto(subscriptionDto({ checkout_url: "javascript:alert(1)" })),
      PLANS,
    );
    expect(script.checkoutUrl).toBeNull();
    expect(statusLabel("past_due")).toBe("Past due");
  });
});
