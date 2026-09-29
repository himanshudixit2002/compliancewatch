import { stateOf } from "@/entities/consent/mappers";
import type { ConsentPurpose, ConsentSummary, NewConsent } from "@/entities/consent/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isE164 } from "@/shared/lib/identifiers";
import { normalisePhone } from "./form";
import { OPTIONAL_PURPOSES, noticeFor, type DocumentVersions } from "./purposes";
import { changeEvidence, type ConsentChange } from "./settings";

/**
 * The consents settings page's change form and what it records.
 *
 * The form posts the purpose, the change (give or withdraw) and, for WhatsApp reminders, the
 * number. Only the optional purposes are accepted. Giving WhatsApp reminders needs the number
 * (as on the consent step, the number is opted in once the consent is recorded); withdrawing
 * them takes the number when one is known, to opt it out, and records the withdrawal without
 * one otherwise, because a withdrawal must never wait on anything else.
 *
 * A change that is already the current state records nothing: giving what is already given at
 * the current notice version, or withdrawing what is not given. A withdrawal carries the notice
 * version of the grant it withdraws.
 */
export const CHANGE_FIELDS = {
  purpose: "purpose",
  change: "change",
  number: "whatsapp_number",
} as const;

export interface ConsentChangeChoice {
  purpose: ConsentPurpose;
  change: ConsentChange;
  /** E.164, set only for WhatsApp reminders. */
  whatsappNumber: string | null;
}

export type ParsedConsentChange =
  | { ok: true; value: ConsentChangeChoice }
  | { ok: false; fieldErrors?: FieldErrors; formErrors?: readonly string[] };

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function isOptionalPurpose(value: string): value is ConsentPurpose {
  return (OPTIONAL_PURPOSES as readonly string[]).includes(value);
}

export function parseConsentChange(
  formData: FormData,
  options: { offerWhatsapp: boolean },
): ParsedConsentChange {
  const purpose = text(formData, CHANGE_FIELDS.purpose);
  if (!isOptionalPurpose(purpose)) {
    return { ok: false, formErrors: [t("consentSettings.error.purpose")] };
  }
  const change = text(formData, CHANGE_FIELDS.change);
  if (change !== "give" && change !== "withdraw") {
    return { ok: false, formErrors: [t("consentSettings.error.change")] };
  }
  if (purpose !== "whatsapp_reminders")
    return { ok: true, value: { purpose, change, whatsappNumber: null } };
  if (change === "give" && !options.offerWhatsapp) {
    return { ok: false, formErrors: [t("consent.error.whatsappNotOffered")] };
  }
  const number = normalisePhone(text(formData, CHANGE_FIELDS.number));
  if (number === "") {
    if (change === "withdraw")
      return { ok: true, value: { purpose, change, whatsappNumber: null } };
    return {
      ok: false,
      fieldErrors: { [CHANGE_FIELDS.number]: [t("consent.error.whatsappNumberMissing")] },
    };
  }
  if (!isE164(number)) {
    return {
      ok: false,
      fieldErrors: { [CHANGE_FIELDS.number]: [t("consent.error.whatsappNumber")] },
    };
  }
  return { ok: true, value: { purpose, change, whatsappNumber: number } };
}

/** The record the change adds, or null when the change is already the current state. */
export function consentChangeRecord(
  choice: ConsentChangeChoice,
  summary: ConsentSummary,
  versions: DocumentVersions,
  userId: string,
): NewConsent | null {
  const state = stateOf(summary, choice.purpose);
  const base = {
    subject: userId,
    purpose: choice.purpose,
    source: "web_settings" as const,
    evidence: changeEvidence(choice.purpose, choice.change),
    recordedBy: userId,
  };
  if (choice.change === "withdraw") {
    if (state === undefined || !state.granted) return null;
    return { ...base, granted: false, noticeVersion: state.noticeVersion };
  }
  const noticeVersion = noticeFor(choice.purpose, versions);
  if (state !== undefined && state.granted && state.noticeVersion === noticeVersion) return null;
  return { ...base, granted: true, noticeVersion };
}
