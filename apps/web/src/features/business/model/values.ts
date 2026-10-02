import { isValueState } from "@/entities/business/mappers";
import type { Answer, AttributeValue, ValueState } from "@/entities/business/types";
import { allowsValue, optionLabel } from "@/entities/ontology/mappers";
import type { OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { formatDate, isDateKey } from "@/shared/lib/dates";
import { parseFinancialYearLabel } from "@/shared/lib/financial-year";

/**
 * Attribute values between the service's canonical form and what a person reads or types.
 *
 * `formatValue` words a stored value with the ontology's labels (an enum by its label, a set by
 * its labels in the ontology's order, a boolean as Yes or No, a whole number with Indian digit
 * grouping, a date in IST). `parseAnswer` turns a form's state and raw strings into the answer
 * the business API takes, checking only the shape the ontology states (allowed values, bounds,
 * date format) so a person gets a message before the service is asked; the service still
 * validates, and its 422 comes back as the same kind of field error. `formDefault` gives a
 * control its starting value from a stored one.
 */
const WHOLE_NUMBER = /^-?\d+$/;
const DECIMAL_NUMBER = /^-?\d+(\.\d+)?$/;
const NUMBER_FORMAT = new Intl.NumberFormat("en-IN");

function stringsOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

/** A stored value as words; "" for null or undefined (the caller shows the state instead). */
export function formatValue(attribute: OntologyAttribute | undefined, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (attribute === undefined) {
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  switch (attribute.type) {
    case "enum":
    case "ordered_enum":
      return optionLabel(attribute, String(value));
    case "enum_set": {
      const chosen = new Set(stringsOf(value));
      if (chosen.size === 0) return t("attribute.none");
      const known = attribute.options.filter((option) => chosen.has(option.value));
      const unknown = [...chosen].filter(
        (item) => !attribute.options.some((o) => o.value === item),
      );
      return [...known.map((option) => option.label), ...unknown].join(", ");
    }
    case "boolean":
      return value === true
        ? t("attribute.yes")
        : value === false
          ? t("attribute.no")
          : String(value);
    case "integer":
      return typeof value === "number" ? NUMBER_FORMAT.format(value) : String(value);
    case "date":
      return typeof value === "string" && isDateKey(value) ? formatDate(value) : String(value);
    default:
      return String(value);
  }
}

/** What a row or a chip says for a stored value: the value when known, else its state. */
export function describeValue(
  attribute: OntologyAttribute | undefined,
  stored: AttributeValue,
): string {
  return stored.state === "known" ? formatValue(attribute, stored.value) : stateLabel(stored.state);
}

export function stateLabel(state: ValueState): string {
  return t(`attribute.state.${state}`);
}

/** The value a control starts from: a string, or the ticked values of a set. */
export function formDefault(
  attribute: OntologyAttribute,
  stored: AttributeValue | undefined,
): string | string[] | undefined {
  if (stored === undefined || stored.state !== "known" || stored.value === null) return undefined;
  if (attribute.type === "enum_set") return stringsOf(stored.value);
  return String(stored.value);
}

export interface AnswerInput {
  /** The submit button's value: known, unsure or not_applicable. */
  state: string;
  /** Every value the form submitted under the control's name. */
  values: readonly string[];
}

export interface AnswerTarget {
  /** The financial year a per-year answer is for; required for such an attribute. */
  asOfFy?: string | null;
  /** The registration or location the answer is for, when the business has several. */
  nodeId?: string | null;
}

export type ParsedAnswer = { ok: true; answer: Answer } | { ok: false; error: string };

function refuse(error: string): ParsedAnswer {
  return { ok: false, error };
}

function inRange(attribute: OntologyAttribute, value: number): string | null {
  if (attribute.min !== null && value < attribute.min) {
    return t("attribute.error.min", { min: NUMBER_FORMAT.format(attribute.min) });
  }
  if (attribute.max !== null && value > attribute.max) {
    return t("attribute.error.max", { max: NUMBER_FORMAT.format(attribute.max) });
  }
  return null;
}

type KnownValue = { ok: true; value: unknown } | { ok: false; error: string };

function knownValue(attribute: OntologyAttribute, values: readonly string[]): KnownValue {
  const raw = (values[0] ?? "").trim();
  switch (attribute.type) {
    case "enum":
    case "ordered_enum":
      return raw !== "" && allowsValue(attribute, raw)
        ? { ok: true, value: raw }
        : { ok: false, error: t("attribute.error.choose") };
    case "boolean":
      if (raw === "true" || raw === "false") return { ok: true, value: raw === "true" };
      return { ok: false, error: t("attribute.error.choose") };
    case "enum_set": {
      const chosen = new Set(values.map((value) => value.trim()));
      const allowed = attribute.options.filter((option) => chosen.has(option.value));
      if (allowed.length === 0 || allowed.length !== chosen.size) {
        return { ok: false, error: t("attribute.error.chooseAtLeastOne") };
      }
      return { ok: true, value: allowed.map((option) => option.value) };
    }
    case "integer": {
      const compact = raw.replace(/[,\s]/g, "");
      if (!WHOLE_NUMBER.test(compact))
        return { ok: false, error: t("attribute.error.wholeNumber") };
      const value = Number(compact);
      const range = inRange(attribute, value);
      return range === null ? { ok: true, value } : { ok: false, error: range };
    }
    case "decimal": {
      const compact = raw.replace(/[,\s]/g, "");
      if (!DECIMAL_NUMBER.test(compact)) return { ok: false, error: t("attribute.error.number") };
      const range = inRange(attribute, Number(compact));
      // Decimals travel as strings, the kernel's canonical form; no float arithmetic here.
      return range === null ? { ok: true, value: compact } : { ok: false, error: range };
    }
    case "date":
      return isDateKey(raw)
        ? { ok: true, value: raw }
        : { ok: false, error: t("attribute.error.date") };
    case "string":
      return raw !== ""
        ? { ok: true, value: raw }
        : { ok: false, error: t("attribute.error.text") };
  }
}

/**
 * The answer a form submitted, or the message to show under the control. A "not sure" or
 * "does not apply" answer carries no value; a per-year attribute needs its financial year, and
 * any other attribute never sends one.
 */
export function parseAnswer(
  attribute: OntologyAttribute,
  input: AnswerInput,
  target: AnswerTarget = {},
): ParsedAnswer {
  if (!isValueState(input.state)) return refuse(t("attribute.error.state"));
  const answer: Answer = { key: attribute.key, state: input.state };
  if (attribute.perFinancialYear) {
    const fy = target.asOfFy ?? null;
    if (fy === null || parseFinancialYearLabel(fy) === null)
      return refuse(t("attribute.error.year"));
    answer.asOfFy = fy;
  }
  if (target.nodeId !== undefined && target.nodeId !== null) answer.nodeId = target.nodeId;
  if (input.state !== "known") return { ok: true, answer };
  const parsed = knownValue(attribute, input.values);
  if (!parsed.ok) return refuse(parsed.error);
  answer.value = parsed.value;
  return { ok: true, answer };
}
