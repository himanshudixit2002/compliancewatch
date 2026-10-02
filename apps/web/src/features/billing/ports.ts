import type { NewSubscription, Plan, Subscription } from "@/entities/billing/types";
import type { Result } from "@/server/result";

/** What the billing page needs: the plans on offer and starting a subscription for the tenant. */
export interface BillingPort {
  plans(): Promise<Result<readonly Plan[]>>;
  subscribe(input: NewSubscription): Promise<Result<Subscription>>;
}
