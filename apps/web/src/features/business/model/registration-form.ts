import type { RegistrationAdded } from "@/entities/business/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isGstin, isUuid, normaliseIdentifier, panOfGstin } from "@/shared/lib/identifiers";
import { attributeLabel } from "./attributes";
import { NAME_MAX_LENGTH } from "./business-form";

/**
 * The add-a-GSTIN form on a business's profile page: another GSTIN registration of the same
 * business (the same PAN, often another state), added with
 * `POST /v1/businesses/{business_id}/registrations` and the Idempotency-Key the page rendered
 * (`profile.add-registration`), then pre-filled from the GSTIN lookup like the first one. The
 * GSTIN is upper-cased and stripped of spaces and must match the kernel's pattern; a name for the
 * registration is optional (the service uses the business name). The field names are the API's,
 * so a 422's `errors[].loc` lands on the right field. The business travels as a
 * hidden field; the action reads the business before the call, so the form can say plainly when
 * the GSTIN carries another PAN (that is another business, added from the business step).
 */
export const REGISTRATION_FIELDS = {
  businessId: "business_id",
  gstin: "gstin",
  name: "name",
} as const;

export type RegistrationFields = typeof REGISTRATION_FIELDS;

export interface RegistrationFormInput {
  businessId: string;
  gstin: string;
  name?: string;
}

export type ParsedRegistrationForm =
  | { ok: true; value: RegistrationFormInput }
  | { ok: false; fieldErrors?: FieldErrors; formError?: string };

function text(formData: FormData, field: string): string {
  const value = formData.get(field);
  return typeof value === "string" ? value.trim() : "";
}

export function parseRegistrationForm(formData: FormData): ParsedRegistrationForm {
  const businessId = text(formData, REGISTRATION_FIELDS.businessId);
  if (!isUuid(businessId)) return { ok: false, formError: t("question.error.form") };
  const errors: Record<string, string[]> = {};
  const gstin = normaliseIdentifier(text(formData, REGISTRATION_FIELDS.gstin));
  if (gstin === "") errors[REGISTRATION_FIELDS.gstin] = [t("businessStep.error.gstinMissing")];
  else if (!isGstin(gstin)) errors[REGISTRATION_FIELDS.gstin] = [t("businessStep.error.gstin")];
  const name = text(formData, REGISTRATION_FIELDS.name);
  if (name.length > NAME_MAX_LENGTH) {
    errors[REGISTRATION_FIELDS.name] = [t("businessStep.error.tooLong", { max: NAME_MAX_LENGTH })];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: name === "" ? { businessId, gstin } : { businessId, gstin, name } };
}

/** The field error for a GSTIN of another PAN, or null when the GSTIN carries the business's. */
export function panMismatch(gstin: string, pan: string): FieldErrors | null {
  const carried = panOfGstin(gstin);
  if (carried === pan) return null;
  return { [REGISTRATION_FIELDS.gstin]: [t("registration.error.pan", { carried, pan })] };
}

/** What the form shows once the GSTIN is added. */
export interface RegistrationAddedResult {
  registrationId: string;
  gstin: string;
  name: string;
  /** False when the business already held this GSTIN. */
  created: boolean;
  /** False when no lookup provider answered; a verify_registration task was then opened. */
  lookedUp: boolean;
  /** The attributes the pre-fill stored, by their names. */
  applied: readonly string[];
  attributesHref: string;
  reviewTasksHref: string;
}

export interface RegistrationHrefs {
  /** The attributes page of the business; the registration is added as `?node=`. */
  attributes: string;
  reviewTasks: string;
}

export function registrationAddedResult(
  added: RegistrationAdded,
  hrefs: RegistrationHrefs,
): RegistrationAddedResult {
  const { registration, prefill } = added;
  const query = `?${new URLSearchParams({ node: registration.id }).toString()}`;
  return {
    registrationId: registration.id,
    gstin: registration.key,
    name: registration.name,
    created: added.created,
    lookedUp: prefill.lookedUp,
    applied: prefill.applied.map(attributeLabel),
    attributesHref: `${hrefs.attributes}${query}`,
    reviewTasksHref: hrefs.reviewTasks,
  };
}
