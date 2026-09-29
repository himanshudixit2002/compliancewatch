import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";

/**
 * The add-a-location form on a registration: a stable label (a branch code, 1 to 80
 * characters, the location's natural key under its registration) and a name (1 to 200). The
 * business and the registration travel as hidden fields; the action checks the registration is
 * one of the business's before it calls `POST /v1/profile/locations`.
 */
export const LOCATION_FIELDS = {
  businessId: "business_id",
  registrationId: "registration_id",
  label: "label",
  name: "name",
} as const;

export type LocationFields = typeof LOCATION_FIELDS;

export const LABEL_MAX_LENGTH = 80;
export const LOCATION_NAME_MAX_LENGTH = 200;

export interface LocationFormInput {
  businessId: string;
  registrationId: string;
  label: string;
  name: string;
}

export type ParsedLocationForm =
  | { ok: true; value: LocationFormInput }
  | { ok: false; fieldErrors?: FieldErrors; formError?: string };

export function parseLocationForm(formData: FormData): ParsedLocationForm {
  const read = (field: string) => {
    const value = formData.get(field);
    return typeof value === "string" ? value.trim() : "";
  };
  const businessId = read(LOCATION_FIELDS.businessId);
  const registrationId = read(LOCATION_FIELDS.registrationId);
  if (!isUuid(businessId) || !isUuid(registrationId)) {
    return { ok: false, formError: t("question.error.form") };
  }
  const label = read(LOCATION_FIELDS.label);
  const name = read(LOCATION_FIELDS.name);
  const errors: Record<string, string[]> = {};
  if (label === "") errors[LOCATION_FIELDS.label] = [t("location.error.label")];
  else if (label.length > LABEL_MAX_LENGTH) {
    errors[LOCATION_FIELDS.label] = [t("businessStep.error.tooLong", { max: LABEL_MAX_LENGTH })];
  }
  if (name === "") errors[LOCATION_FIELDS.name] = [t("location.error.name")];
  else if (name.length > LOCATION_NAME_MAX_LENGTH) {
    errors[LOCATION_FIELDS.name] = [
      t("businessStep.error.tooLong", { max: LOCATION_NAME_MAX_LENGTH }),
    ];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: { businessId, registrationId, label, name } };
}
