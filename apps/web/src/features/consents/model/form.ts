import type { ConsentPurpose } from "@/entities/consent/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isE164, normalisePhone } from "@/shared/lib/identifiers";
import { ONBOARDING_PURPOSES, REQUIRED_PURPOSES } from "./purposes";

/**
 * The consent form's fields and the shape check of what it posts. Each purpose's checkbox is
 * named after the purpose and submits a value only when ticked; the WhatsApp number is its own
 * field, required when the WhatsApp box is ticked. The number is normalised (spaces, dashes and
 * brackets dropped) and must be E.164; it goes to the notification service in the server
 * action and is never put in a URL the browser sees. The service keys a WhatsApp preference by
 * the number as WhatsApp reports it, digits without the plus (the bot's opt-ins and the seed use
 * that form), so `whatsappRecipient` drops the plus before the call.
 */
export const WHATSAPP_NUMBER_FIELD = "whatsapp_number";

export interface ConsentChoice {
  /** The ticked purposes, in the order they are asked. */
  purposes: ConsentPurpose[];
  /** Set when the WhatsApp box is ticked. */
  whatsappNumber: string | null;
}

export type ParsedConsentForm =
  { ok: true; value: ConsentChoice } | { ok: false; fieldErrors: FieldErrors };

export { normalisePhone };

/** "+919800000000" -> "919800000000": the key WhatsApp and the notification service use. */
export function whatsappRecipient(e164: string): string {
  return e164.replace(/^\+/, "");
}

export function parseConsentForm(
  formData: FormData,
  options: { offerWhatsapp: boolean },
): ParsedConsentForm {
  const errors: Record<string, string[]> = {};
  const purposes = ONBOARDING_PURPOSES.filter((purpose) => formData.get(purpose) !== null);
  for (const purpose of REQUIRED_PURPOSES) {
    if (!purposes.includes(purpose)) errors[purpose] = [t("consent.error.required")];
  }
  let whatsappNumber: string | null = null;
  if (purposes.includes("whatsapp_reminders")) {
    const raw = formData.get(WHATSAPP_NUMBER_FIELD);
    const number = normalisePhone(typeof raw === "string" ? raw : "");
    if (!options.offerWhatsapp) {
      errors.whatsapp_reminders = [t("consent.error.whatsappNotOffered")];
    } else if (number === "") {
      errors[WHATSAPP_NUMBER_FIELD] = [t("consent.error.whatsappNumberMissing")];
    } else if (!isE164(number)) {
      errors[WHATSAPP_NUMBER_FIELD] = [t("consent.error.whatsappNumber")];
    } else {
      whatsappNumber = number;
    }
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: { purposes, whatsappNumber } };
}
