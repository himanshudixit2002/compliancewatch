import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type { PlanView } from "../model/plans";
import { SubscribeForm, type SubscribeAction, type SubscribeFormProps } from "./subscribe-form";

export interface BillingViewProps {
  title: string;
  plans: readonly PlanView[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  action: SubscribeAction;
  fields: SubscribeFormProps["fields"];
}

/**
 * The billing page: the plans the identity service offers, each with its price, period and the
 * service's own description, and the form that starts a subscription with the provider.
 */
export function BillingView({ title, plans, crumbs, tabs, action, fields }: BillingViewProps) {
  return (
    <div data-slot="billing" className="flex max-w-4xl flex-col gap-8">
      <SettingsHeader title={title} description={t("billing.intro")} crumbs={crumbs} tabs={tabs} />
      <section aria-labelledby="billing-plans" className="flex flex-col gap-3">
        <h2 id="billing-plans" className="text-lg font-semibold text-fg">
          {t("billing.plansTitle")}
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2" data-slot="plans">
          {plans.map((plan) => (
            <li
              key={plan.key}
              data-plan={plan.key}
              className="flex flex-col gap-1 rounded-md border border-line bg-surface p-4"
            >
              <h3 className="font-semibold text-fg">{plan.name}</h3>
              <p className="text-fg">
                <span className="text-xl font-semibold">{plan.price}</span>{" "}
                <span className="text-sm text-fg-muted">{plan.period}</span>
              </p>
              {plan.description === "" ? null : (
                <p className="text-sm text-fg-muted">{plan.description}</p>
              )}
              <p className="text-xs text-fg-muted">
                {t("billing.planKey")}: <code>{plan.key}</code>
              </p>
            </li>
          ))}
        </ul>
        <p className="text-sm text-fg-muted">{t("billing.pricesFrom")}</p>
      </section>
      <section aria-labelledby="billing-subscribe" className="flex flex-col gap-3">
        <h2 id="billing-subscribe" className="text-lg font-semibold text-fg">
          {t("billing.subscribeTitle")}
        </h2>
        <SubscribeForm action={action} plans={plans} fields={fields} />
      </section>
    </div>
  );
}
