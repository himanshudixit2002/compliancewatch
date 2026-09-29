import type { Plan, Subscription } from "@/entities/billing/types";
import { formatDateTime } from "@/shared/lib/dates";

/**
 * A started subscription as the page shows it: the plan's name, the provider's status and id,
 * when it started in IST, and the provider's checkout page when it returned one (an http or
 * https address only; anything else is not offered as a link).
 */
export interface SubscriptionView {
  planName: string;
  status: string;
  providerSubscriptionId: string;
  startedAt: string;
  checkoutUrl: string | null;
}

export function statusLabel(status: string): string {
  const words = status.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function safeCheckoutUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function subscriptionView(
  subscription: Subscription,
  plans: readonly Plan[],
): SubscriptionView {
  const plan = plans.find((candidate) => candidate.key === subscription.planKey);
  return {
    planName: plan?.name ?? subscription.planKey,
    status: statusLabel(subscription.status),
    providerSubscriptionId: subscription.providerSubscriptionId,
    startedAt: formatDateTime(subscription.startedAt),
    checkoutUrl: safeCheckoutUrl(subscription.checkoutUrl),
  };
}
