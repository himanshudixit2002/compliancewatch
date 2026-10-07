import type { NewSubscription, Plan, Subscription } from "@/entities/billing/types";
import type { Result } from "@/server/result";

/** Request headers a write carries: the Idempotency-Key the form minted. */
export type RequestHeaders = Readonly<Record<string, string>>;

/**
 * What the billing page needs: the plans on offer and starting a subscription for the tenant.
 * Starting one carries the Idempotency-Key the form minted for the attempt
 * (`idempotencyHeaders(formData, "identity.start-subscription")`), so a double submit or a retry
 * starts one subscription with the provider.
 */
export interface BillingPort {
  plans(): Promise<Result<readonly Plan[]>>;
  subscribe(input: NewSubscription, idempotency: RequestHeaders): Promise<Result<Subscription>>;
}
