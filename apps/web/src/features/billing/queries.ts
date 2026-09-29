import "server-only";

import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { mapResult, type Result } from "@/server/result";
import { billingGateway } from "./gateway";
import { planView, type PlanView } from "./model/plans";

/** The billing page's read: the plans on offer, from the identity service. */
export interface BillingPageView {
  plans: readonly PlanView[];
}

export async function getBillingPage(
  session: ClientPrincipal,
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<Result<BillingPageView>> {
  const plans = await billingGateway({ session, fetchImpl: deps.fetchImpl }).plans();
  return mapResult(plans, (value) => ({ plans: value.map(planView) }));
}
