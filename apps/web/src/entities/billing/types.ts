import type { identity } from "@compliancewatch/contracts/openapi";

/**
 * Billing on the identity service: the plans on offer (placeholders with zero prices until
 * pricing is decided, as the service's own descriptions say) and a subscription started with the
 * billing provider, which hosts the checkout; no card data passes through the web app. With no
 * provider connected (`CW_BILLING_PROVIDER=none`) starting one answers 503 `billing-disabled`.
 */
type Schemas = identity.components["schemas"];

export type PlanDto = Schemas["PlanOut"];
export type SubscriptionInDto = Schemas["SubscriptionIn"];
export type SubscriptionDto = Schemas["SubscriptionOut"];

/** The problem slug the subscriptions route answers when no billing provider is connected. */
export const BILLING_DISABLED = "billing-disabled";

export interface Plan {
  key: string;
  name: string;
  /** Integer paise. */
  amountPaise: number;
  /** "monthly" or "yearly" on main. */
  period: string;
  description: string;
}

export interface NewSubscription {
  planKey: string;
  /** The billing contact's address, sent to the provider. */
  email: string;
  name: string;
}

export interface Subscription {
  planKey: string;
  providerSubscriptionId: string;
  /** created, active, past_due or cancelled. */
  status: string;
  startedAt: string;
  /** The provider's hosted checkout; empty when the provider returned none. */
  checkoutUrl: string;
}
