import type { NewBusiness } from "@/entities/business/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isGstin, normaliseIdentifier } from "@/shared/lib/identifiers";

/**
 * The business step's form: the GSTIN, the name the business goes by, and an optional name for
 * the registration. The check here is the shape the business API validates (a GSTIN of the
 * kernel's pattern after spaces are removed and letters upper-cased, a name of 1 to 200
 * characters), so a person sees the message before any call; the service checks again and its
 * 422 comes back as the same field errors. The field names are the API's, so a 422's
 * `errors[].loc` lands on the right field.
 */
export const BUSINESS_FORM_FIELDS = {
  gstin: "gstin",
  name: "name",
  registrationName: "registration_name",
} as const;

export type BusinessFormFields = typeof BUSINESS_FORM_FIELDS;

/** The business API's limit on a business or registration name. */
export const NAME_MAX_LENGTH = 200;

export type ParsedBusinessForm =
  { ok: true; value: NewBusiness & { gstin: string } } | { ok: false; fieldErrors: FieldErrors };

function text(formData: FormData, field: string): string {
  const value = formData.get(field);
  return typeof value === "string" ? value.trim() : "";
}

export function parseBusinessForm(formData: FormData): ParsedBusinessForm {
  const errors: Record<string, string[]> = {};
  const gstin = normaliseIdentifier(text(formData, BUSINESS_FORM_FIELDS.gstin));
  if (gstin === "") errors[BUSINESS_FORM_FIELDS.gstin] = [t("businessStep.error.gstinMissing")];
  else if (!isGstin(gstin)) errors[BUSINESS_FORM_FIELDS.gstin] = [t("businessStep.error.gstin")];

  const name = text(formData, BUSINESS_FORM_FIELDS.name);
  if (name === "") errors[BUSINESS_FORM_FIELDS.name] = [t("businessStep.error.name")];
  else if (name.length > NAME_MAX_LENGTH) {
    errors[BUSINESS_FORM_FIELDS.name] = [t("businessStep.error.tooLong", { max: NAME_MAX_LENGTH })];
  }

  const registrationName = text(formData, BUSINESS_FORM_FIELDS.registrationName);
  if (registrationName.length > NAME_MAX_LENGTH) {
    errors[BUSINESS_FORM_FIELDS.registrationName] = [
      t("businessStep.error.tooLong", { max: NAME_MAX_LENGTH }),
    ];
  }

  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  const value: NewBusiness & { gstin: string } = { name, gstin };
  if (registrationName !== "") value.registrationName = registrationName;
  return { ok: true, value };
}
