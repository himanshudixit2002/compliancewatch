import { isUuid } from "@/shared/lib/identifiers";
import { parseFinancialYearLabel } from "@/shared/lib/financial-year";
import type { FieldErrors } from "@/shared/lib/action-state";

/**
 * The fields an answer form posts: which business and node, which attribute and year (hidden
 * inputs the page fills in), the state (the submit button pressed) and the value(s) of the
 * control. `readAnswerForm` checks the hidden part's shape so a tampered form is refused before
 * any call; the value itself is parsed against the ontology by `parseAnswer`.
 */
export const ANSWER_FIELDS = {
  businessId: "business_id",
  nodeId: "node_id",
  key: "key",
  asOfFy: "as_of_fy",
  state: "state",
  value: "value",
} as const;

export type AnswerFields = typeof ANSWER_FIELDS;

const ATTRIBUTE_KEY = /^[a-z][a-z0-9_]{0,63}$/;

export interface AnswerFormInput {
  businessId: string;
  nodeId: string;
  key: string;
  asOfFy: string | null;
  state: string;
  values: string[];
}

function text(formData: FormData, field: string): string {
  const value = formData.get(field);
  return typeof value === "string" ? value.trim() : "";
}

export function isAttributeKey(value: string): boolean {
  return ATTRIBUTE_KEY.test(value);
}

/** The hidden fields and the answer, or null when a hidden field is malformed. */
export function readAnswerForm(formData: FormData): AnswerFormInput | null {
  const businessId = text(formData, ANSWER_FIELDS.businessId);
  const nodeId = text(formData, ANSWER_FIELDS.nodeId);
  const key = text(formData, ANSWER_FIELDS.key);
  const year = text(formData, ANSWER_FIELDS.asOfFy);
  if (!isUuid(businessId) || !isUuid(nodeId) || !isAttributeKey(key)) return null;
  if (year !== "" && parseFinancialYearLabel(year) === null) return null;
  return {
    businessId,
    nodeId,
    key,
    asOfFy: year === "" ? null : year,
    state: text(formData, ANSWER_FIELDS.state),
    values: formData
      .getAll(ANSWER_FIELDS.value)
      .filter((value): value is string => typeof value === "string"),
  };
}

/**
 * A 422 from `PATCH /v1/businesses/{id}` names the field inside the change list
 * (`changes.0.value`); the form has one control, so those land on it and the rest on the form.
 */
export function answerFieldErrors(fieldErrors: FieldErrors | undefined): {
  value: string[];
  form: string[];
} {
  const value: string[] = [];
  const form: string[] = [];
  for (const [path, messages] of Object.entries(fieldErrors ?? {})) {
    (path === "value" || path.endsWith(".value") ? value : form).push(...messages);
  }
  return { value, form };
}
