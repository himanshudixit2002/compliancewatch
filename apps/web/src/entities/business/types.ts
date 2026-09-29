import type { profile } from "@compliancewatch/contracts/openapi";

/**
 * A business and its profile, as the profile service's business API and node routes return
 * them (ADR-016). A business is a legal entity (its PAN) with the GSTIN registrations under it;
 * its id is the entity node's id. Each node holds attribute values, which inherit downward
 * (entity to registration to location). Onboarding is the business API's checklist: the one
 * question to ask next, with its wording and options, and the progress.
 *
 * The domain names are camel case; the mappers own the translation from the wire. Attribute
 * types, levels and labels belong to the ontology (entities/ontology); here a value is stored
 * data only.
 */
type Schemas = profile.components["schemas"];

export type AttributeValueDto = Schemas["AttributeOut"];
export type ProfileNodeDto = Schemas["NodeOut"];
export type BusinessDto = Schemas["BusinessOut"];
export type BusinessSummaryDto = Schemas["BusinessSummaryOut"];
export type BusinessPageDto = Schemas["Page_BusinessSummaryOut_"];
export type BusinessCreatedDto = Schemas["BusinessCreatedOut"];
export type RegistrationCreatedDto = Schemas["RegistrationCreatedOut"];
export type OnboardingDto = Schemas["OnboardingOut"];
export type QuestionDto = Schemas["QuestionOut"];
export type PrefillDto = Schemas["PrefillOut"];
export type LookupResultDto = Schemas["LookupResultOut"];
export type ReviewTaskDto = Schemas["ReviewTaskOut"];
export type SnapshotDto = Schemas["SnapshotOut"];
export type BusinessInDto = Schemas["BusinessIn"];
export type BusinessPatchInDto = Schemas["BusinessPatchIn"];
export type BusinessChangeInDto = Schemas["BusinessChangeIn"];
export type RegistrationAddInDto = Schemas["RegistrationAddIn"];
export type LocationInDto = Schemas["LocationIn"];

/** How sure the answer is: a value, "not sure", or "does not apply" (ValueState). */
export const VALUE_STATES = ["known", "unsure", "not_applicable"] as const;

export type ValueState = (typeof VALUE_STATES)[number];

/** Where one onboarding question stands (ItemState): the checklist asks missing and unsure. */
export type QuestionState = "missing" | "unsure" | "known" | "not_applicable";

export interface AttributeValue {
  key: string;
  state: ValueState;
  /** The value in canonical form; null for unsure and not_applicable. */
  value: unknown;
  /** The financial year a per-year value is stated for ("2026-27"); null otherwise. */
  asOfFy: string | null;
  /** gstin_lookup, user_input or derived. */
  source: string;
  updatedAt: string | null;
}

export interface ProfileNode {
  id: string;
  /** entity, registration or location. */
  level: string;
  /** The PAN of an entity, the GSTIN of a registration, the label of a location. */
  key: string;
  name: string;
  parentId: string | null;
  version: number;
  attributes: readonly AttributeValue[];
  /** True when the call that returned it created it. */
  created: boolean;
}

export interface Business {
  /** The entity node's id. */
  id: string;
  name: string;
  pan: string;
  version: number;
  createdAt: string;
  updatedAt: string;
  /** Values stored on the legal entity. */
  attributes: readonly AttributeValue[];
  /** Its GSTIN registrations, oldest first. */
  registrations: readonly ProfileNode[];
}

export interface BusinessSummary {
  id: string;
  name: string;
  pan: string;
  gstins: readonly string[];
  updatedAt: string;
}

export interface BusinessPage {
  items: readonly BusinessSummary[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

export interface QuestionOption {
  value: string;
  label: string;
}

/** The one question onboarding asks next, worded by the ontology. */
export interface Question {
  /** The entity or registration the answer is stored on. */
  nodeId: string;
  level: string;
  key: string;
  state: QuestionState;
  perFinancialYear: boolean;
  /** The year a per-year answer is for; null otherwise. */
  asOfFy: string | null;
  type: string;
  question: string;
  help: string;
  options: readonly QuestionOption[];
  min: number | null;
  max: number | null;
}

export interface Onboarding {
  businessId: string;
  /** The financial year per-year questions are asked for. */
  asOfFy: string;
  answered: number;
  total: number;
  complete: boolean;
  /** Null when complete. */
  next: Question | null;
}

export interface LookupResult {
  gstin: string;
  legalName: string;
  tradeName: string;
  registrationType: string;
  gstinStatus: string;
  stateCode: string;
  constitution: string;
  registeredSince: string | null;
  businessCategory: string;
  natureOfBusiness: readonly string[];
}

/** What the GSTIN filled in: the lookup's answer and the attribute keys it stored. */
export interface Prefill {
  nodeId: string;
  /** False when no lookup provider answered; a verify_registration task is then opened. */
  lookedUp: boolean;
  result: LookupResult | null;
  applied: readonly string[];
  reviewTaskId: string | null;
}

export interface BusinessCreated {
  business: Business;
  /** False when the tenant already had this business (the same PAN). */
  created: boolean;
  /** Null when the business was created from a PAN alone. */
  prefill: Prefill | null;
  onboarding: Onboarding;
}

export interface RegistrationAdded {
  business: Business;
  registration: ProfileNode;
  /** False when the business already held this GSTIN. */
  created: boolean;
  prefill: Prefill;
}

export interface ReviewTask {
  id: string;
  nodeId: string;
  attributeKey: string;
  /** not_applicable, confirm_financial_year or verify_registration. */
  reason: string;
  asOfFy: string | null;
  open: boolean;
  createdAt: string;
}

/** What the applicability engine evaluates: a node's values with inheritance applied. */
export interface Snapshot {
  /** The node the snapshot is for (the service names it business_id). */
  businessId: string;
  tenantId: string;
  version: number;
  level: string | null;
  /** The node's ancestors from the entity down, without the node itself. */
  lineage: readonly string[];
  asOfFy: string | null;
  attributes: Readonly<Record<string, unknown>>;
}

/** One answer to store. */
export interface Answer {
  key: string;
  state: ValueState;
  /** Absent for unsure and not_applicable. */
  value?: unknown;
  /** Required for a per-year attribute. */
  asOfFy?: string | null;
  /** The registration or location it is for; the attribute's level picks the node without it. */
  nodeId?: string | null;
}

export interface NewBusiness {
  name: string;
  /** Any case or spacing; its PAN makes the business and the registration is pre-filled. */
  gstin?: string;
  /** Enough on its own when there is no GSTIN yet. */
  pan?: string;
  registrationName?: string;
  answers?: readonly Answer[];
}

export interface BusinessChanges {
  name?: string;
  /** All of them or none are stored. */
  changes?: readonly Answer[];
}

export interface NewRegistration {
  gstin: string;
  name?: string;
}

export interface NewLocation {
  registrationId: string;
  /** A stable label such as a branch code, 1 to 80 characters. */
  label: string;
  name: string;
}

export interface BusinessListQuery {
  /** Keeps the businesses whose name, PAN or GSTIN contains this. */
  q?: string;
  limit?: number;
  cursor?: string;
}
