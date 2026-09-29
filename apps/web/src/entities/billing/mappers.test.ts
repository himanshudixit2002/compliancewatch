import { describe, expect, it } from "vitest";
import { newSubscriptionToDto, planFromDto, subscriptionFromDto } from "./mappers";

describe("billing mappers", () => {
  it("maps a plan", () => {
    expect(
      planFromDto({
        key: "example_plan",
        name: "Example plan",
        amount_paise: 0,
        period: "monthly",
        description: "Example description",
      }),
    ).toEqual({
      key: "example_plan",
      name: "Example plan",
      amountPaise: 0,
      period: "monthly",
      description: "Example description",
    });
  });

  it("maps a new subscription out and a started one back", () => {
    expect(
      newSubscriptionToDto({ planKey: "example_plan", email: "a@example.com", name: "Example" }),
    ).toEqual({ plan_key: "example_plan", email: "a@example.com", name: "Example" });
    expect(
      subscriptionFromDto({
        plan_key: "example_plan",
        provider_subscription_id: "sub_example_1",
        status: "created",
        started_at: "2000-01-01T00:00:00Z",
        checkout_url: "",
      }),
    ).toEqual({
      planKey: "example_plan",
      providerSubscriptionId: "sub_example_1",
      status: "created",
      startedAt: "2000-01-01T00:00:00Z",
      checkoutUrl: "",
    });
  });
});
