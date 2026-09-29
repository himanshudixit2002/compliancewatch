import type {
  NewSubscription,
  Plan,
  PlanDto,
  Subscription,
  SubscriptionDto,
  SubscriptionInDto,
} from "./types";

export function planFromDto(dto: PlanDto): Plan {
  return {
    key: dto.key,
    name: dto.name,
    amountPaise: dto.amount_paise,
    period: dto.period,
    description: dto.description,
  };
}

export function newSubscriptionToDto(input: NewSubscription): SubscriptionInDto {
  return { plan_key: input.planKey, email: input.email, name: input.name };
}

export function subscriptionFromDto(dto: SubscriptionDto): Subscription {
  return {
    planKey: dto.plan_key,
    providerSubscriptionId: dto.provider_subscription_id,
    status: dto.status,
    startedAt: dto.started_at,
    checkoutUrl: dto.checkout_url,
  };
}
