import "server-only";

import { newSubscriptionToDto, planFromDto, subscriptionFromDto } from "@/entities/billing/mappers";
import type { NewSubscription, Plan, Subscription } from "@/entities/billing/types";
import { call } from "@/server/api/client";
import { identityClient, type ClientContext, type IdentityClient } from "@/server/api/services";
import { cachedRead, tags } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { BillingPort } from "./ports";

/**
 * Billing over the typed identity client. The plans are the same for every tenant and are kept
 * for five minutes under `identity:plans`; a subscription is started for the session's tenant
 * (x-tenant-id) and is never retried or cached. The route takes no Idempotency-Key: a second
 * submit starts a second subscription with the provider, so the form disables itself while one
 * is pending.
 */
export class BillingGateway implements BillingPort {
  private readonly identity: IdentityClient;

  constructor(ctx: ClientContext) {
    this.identity = identityClient(ctx);
  }

  async plans(): Promise<Result<readonly Plan[]>> {
    const result = await call(
      this.identity.GET("/v1/identity/billing/plans", {
        ...cachedRead([tags.identity.plans()]),
      }),
    );
    return mapBody(result, (plans) => plans.map(planFromDto));
  }

  async subscribe(input: NewSubscription): Promise<Result<Subscription>> {
    const result = await call(
      this.identity.POST("/v1/identity/billing/subscriptions", {
        body: newSubscriptionToDto(input),
      }),
    );
    return mapBody(result, subscriptionFromDto);
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function billingGateway(ctx: ClientContext): BillingGateway {
  return new BillingGateway(ctx);
}
