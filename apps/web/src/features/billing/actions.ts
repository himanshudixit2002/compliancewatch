"use server";

import { track } from "@/server/analytics";
import { idempotencyHeaders } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { billingGateway } from "./gateway";
import { parseSubscribeForm } from "./model/subscribe-form";
import { subscriptionView, type SubscriptionView } from "./model/subscription";

/**
 * Starts a subscription for the tenant: the screen's gate again (owner or CA admin), the
 * billing capability, the form's shape against the plans the service offers, then `POST
 * /v1/identity/billing/subscriptions` with the Idempotency-Key the form was rendered with. The service's answer is the result: the subscription
 * with its checkout page, or its problem. With no billing provider connected that problem is 503
 * `billing-disabled`, which the form shows as "billing is not connected" rather than as a
 * failure; nothing was started and nothing was charged.
 */
export async function startSubscription(
  _state: ActionState<SubscriptionView>,
  formData: FormData,
): Promise<ActionState<SubscriptionView>> {
  const session = await requireScreenSession(screenById("owner.settings.billing"));
  if (!can(session, "billing.manage")) return actionFailure(t("billing.error.role"));
  const gateway = billingGateway({ session });
  const plans = await gateway.plans();
  if (!plans.ok) return toActionState(plans);
  const parsed = parseSubscribeForm(
    formData,
    plans.value.map((plan) => plan.key),
  );
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const started = await gateway.subscribe(
    parsed.value,
    idempotencyHeaders(formData, "identity.start-subscription"),
  );
  if (!started.ok) return toActionState(started);
  await track(session, {
    name: "subscription_started",
    properties: { plan_key: parsed.value.planKey },
  });
  return actionSuccess(subscriptionView(started.value, plans.value));
}
