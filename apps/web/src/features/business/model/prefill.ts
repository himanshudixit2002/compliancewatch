import type { BusinessCreated, LookupResult } from "@/entities/business/types";
import { attributeOf } from "@/entities/ontology/mappers";
import type { Ontology } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import { formatDate, isDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { attributeLabel } from "./attributes";
import { formatValue } from "./values";
import { onboardingProgress } from "./progress";

/**
 * What the business step shows once `POST /v1/businesses` answered: whether the business is new
 * or was already on file, and what the GSTIN lookup returned. Every value in the table is the
 * lookup's own answer, worded with the ontology's labels where the ontology has the attribute
 * (registration type, GSTIN status, constitution, the state, the date); nothing is filled in by
 * the web app. Without a lookup answer there is no table, only the review task the service
 * opened so the registration is verified later.
 */
export interface PrefillRow {
  key: string;
  label: string;
  value: string;
}

export interface BusinessStepResult {
  businessId: string;
  businessName: string;
  pan: string;
  gstin: string;
  /** False when the tenant already had a business with this PAN. */
  created: boolean;
  /** False when no lookup provider answered for the GSTIN. */
  lookedUp: boolean;
  rows: readonly PrefillRow[];
  /** The attributes the pre-fill stored, by their names. */
  applied: readonly string[];
  /** The verify_registration task opened when the lookup had nothing. */
  reviewTaskId: string | null;
  progressText: string;
  complete: boolean;
  /** Where the flow goes on: the questions, or the summary when nothing is left to ask. */
  nextHref: string;
}

export interface StepHrefs {
  questions: string;
  done: string;
}

/** Lookup fields in the order the table shows them, with the ontology key that words each. */
const LOOKUP_FIELDS: readonly {
  field: keyof LookupResult;
  label: MessageKey;
  attribute?: string;
}[] = [
  { field: "legalName", label: "prefill.legalName" },
  { field: "tradeName", label: "prefill.tradeName" },
  { field: "registrationType", label: "prefill.registrationType", attribute: "registration_type" },
  { field: "gstinStatus", label: "prefill.gstinStatus", attribute: "gstin_status" },
  { field: "stateCode", label: "prefill.state", attribute: "state_codes" },
  { field: "constitution", label: "prefill.constitution", attribute: "constitution" },
  { field: "registeredSince", label: "prefill.registeredSince", attribute: "registered_since" },
  {
    field: "businessCategory",
    label: "prefill.businessCategory",
    attribute: "business_category",
  },
  { field: "natureOfBusiness", label: "prefill.natureOfBusiness" },
];

function worded(ontology: Ontology | null, key: string | undefined, raw: unknown): string {
  const attribute = ontology === null || key === undefined ? undefined : attributeOf(ontology, key);
  if (key === "state_codes" && typeof raw === "string") {
    // The lookup names one state; the ontology's set of states words it.
    const label = attribute === undefined ? "" : formatValue(attribute, [raw]);
    return label === "" || label === raw ? raw : `${raw} (${label})`;
  }
  if (attribute !== undefined) return formatValue(attribute, raw);
  if (typeof raw === "string" && isDateKey(raw)) return formatDate(raw);
  return typeof raw === "string" ? humanise(raw) : String(raw);
}

/** The looked-up values as rows; empty fields are left out rather than shown blank. */
export function lookupRows(result: LookupResult, ontology: Ontology | null): PrefillRow[] {
  const rows: PrefillRow[] = [];
  for (const { field, label, attribute } of LOOKUP_FIELDS) {
    const raw = result[field];
    if (raw === null || raw === "" || (Array.isArray(raw) && raw.length === 0)) continue;
    const value =
      field === "legalName" || field === "tradeName"
        ? String(raw)
        : Array.isArray(raw)
          ? raw.join(", ")
          : worded(ontology, attribute, raw);
    rows.push({ key: field, label: t(label), value });
  }
  return rows;
}

export function businessStepResult(
  created: BusinessCreated,
  gstin: string,
  ontology: Ontology | null,
  hrefs: StepHrefs,
): BusinessStepResult {
  const { business, prefill, onboarding } = created;
  const progress = onboardingProgress(onboarding);
  return {
    businessId: business.id,
    businessName: business.name,
    pan: business.pan,
    gstin,
    created: created.created,
    lookedUp: prefill?.lookedUp ?? false,
    rows: prefill?.result ? lookupRows(prefill.result, ontology) : [],
    applied: (prefill?.applied ?? []).map(attributeLabel),
    reviewTaskId: prefill?.reviewTaskId ?? null,
    progressText: progress.text,
    complete: progress.complete,
    nextHref: progress.complete ? hrefs.done : hrefs.questions,
  };
}
