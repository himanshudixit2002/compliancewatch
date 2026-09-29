import type { Plan } from "@/entities/billing/types";
import { isMessageKey, t } from "@/shared/i18n";
import { formatPaise } from "@/shared/lib/money";

/**
 * A plan as the page shows it: its name, the price the identity service states (in paise,
 * formatted as rupees) with its period, and the service's own description, which says when a
 * price is a placeholder. Nothing here decides or rounds a price.
 */
export interface PlanView {
  key: string;
  name: string;
  price: string;
  period: string;
  description: string;
}

export function periodLabel(period: string): string {
  const key = `billing.period.${period}`;
  return isMessageKey(key) ? t(key) : period;
}

export function planView(plan: Plan): PlanView {
  return {
    key: plan.key,
    name: plan.name,
    price: formatPaise(plan.amountPaise),
    period: periodLabel(plan.period),
    description: plan.description,
  };
}
