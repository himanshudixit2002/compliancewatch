import type { PlanDto, SubscriptionDto } from "@/entities/billing/types";

/**
 * Identity billing bodies for unit tests: synthetic plans and a subscription as a provider
 * would return one. The e2e suite reads the service's own plans.
 */
export const PLAN_DTOS: PlanDto[] = [
  {
    key: "example_monthly",
    name: "Example monthly plan",
    amount_paise: 149900,
    period: "monthly",
    description: "Example description.",
    limits: { registrations: 5, seats: 3 },
  },
  {
    key: "example_yearly",
    name: "Example yearly plan",
    amount_paise: 0,
    period: "yearly",
    description: "",
    limits: { registrations: null, seats: null },
  },
];

export function subscriptionDto(overrides: Partial<SubscriptionDto> = {}): SubscriptionDto {
  return {
    plan_key: "example_monthly",
    provider_subscription_id: "sub_example_1",
    status: "created",
    started_at: "2000-01-01T00:00:00Z",
    checkout_url: "https://checkout.example.com/sub_example_1",
    quantity: 1,
    ...overrides,
  };
}
