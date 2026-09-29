import type { NewSubscription } from "@/entities/billing/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { EMAIL_MAX_LENGTH, isEmailAddress } from "@/shared/lib/identifiers";

/**
 * The subscribe form's fields and their shape check, mirroring the identity service's
 * SubscriptionIn: a plan the service offers, the billing contact's email (3 to 254 characters)
 * and name (1 to 200). No card or bank detail is ever a field: the provider's checkout page
 * collects payment.
 */
export const SUBSCRIBE_FIELDS = { plan: "plan_key", email: "email", name: "name" } as const;

export const NAME_MAX_LENGTH = 200;

export type ParsedSubscribeForm =
  { ok: true; value: NewSubscription } | { ok: false; fieldErrors: FieldErrors };

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export function parseSubscribeForm(
  formData: FormData,
  planKeys: readonly string[],
): ParsedSubscribeForm {
  const errors: Record<string, string[]> = {};
  const planKey = text(formData, SUBSCRIBE_FIELDS.plan);
  if (!planKeys.includes(planKey)) errors[SUBSCRIBE_FIELDS.plan] = [t("billing.error.plan")];
  const email = text(formData, SUBSCRIBE_FIELDS.email);
  if (email === "") errors[SUBSCRIBE_FIELDS.email] = [t("billing.error.emailMissing")];
  else if (email.length > EMAIL_MAX_LENGTH || !isEmailAddress(email)) {
    errors[SUBSCRIBE_FIELDS.email] = [t("notifications.error.email")];
  }
  const name = text(formData, SUBSCRIBE_FIELDS.name);
  if (name === "") errors[SUBSCRIBE_FIELDS.name] = [t("billing.error.nameMissing")];
  else if (name.length > NAME_MAX_LENGTH) {
    errors[SUBSCRIBE_FIELDS.name] = [t("billing.error.nameTooLong", { max: NAME_MAX_LENGTH })];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: { planKey, email, name } };
}
