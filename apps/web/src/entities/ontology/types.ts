import type { profile } from "@compliancewatch/contracts/openapi";

/**
 * The ontology: the business attributes a profile holds, as `GET /v1/ontology` serves them
 * (the profile service reads packages/ontology's attributes.yaml and wording.en.yaml). Every
 * word the screens show about an attribute comes from here: the question onboarding asks, the
 * help line, the label of each allowed value, and the operators a rule may use on its type.
 * Nothing in the web app restates regulatory wording of its own.
 *
 * The wire shape is the profile spec's; the domain shape below names the kinds the kernel
 * defines (domain_kernel.ontology) so a view can switch on them. An attribute whose type, level
 * or source is not one of those is left out of `attributes` and its key listed in
 * `unsupported`, so a new kind on the service is reported rather than drawn as the wrong control.
 */
export type OntologyDto = profile.components["schemas"]["OntologyOut"];
export type OntologyAttributeDto = profile.components["schemas"]["OntologyAttributeOut"];

/** domain_kernel.ontology.AttributeType: the value type, which decides the control. */
export const ATTRIBUTE_TYPES = [
  "enum",
  "ordered_enum",
  "enum_set",
  "boolean",
  "integer",
  "decimal",
  "date",
  "string",
] as const;

export type AttributeType = (typeof ATTRIBUTE_TYPES)[number];

/** The node of the business hierarchy holding the value (ADR-016); values inherit downward. */
export const ATTRIBUTE_LEVELS = ["entity", "registration", "location"] as const;

export type AttributeLevel = (typeof ATTRIBUTE_LEVELS)[number];

/** Where the value comes from: pre-filled from the GSTIN, asked, or computed by the service. */
export const ATTRIBUTE_SOURCES = ["gstin_lookup", "user_input", "derived"] as const;

export type AttributeSource = (typeof ATTRIBUTE_SOURCES)[number];

/** The wording's review state; `needs_review` until an analyst has read every line. */
export const WORDING_NEEDS_REVIEW = "needs_review";

export interface OntologyOption {
  value: string;
  label: string;
}

export interface OntologyAttribute {
  key: string;
  type: AttributeType;
  level: AttributeLevel;
  source: AttributeSource;
  /** A value stated for one financial year (a turnover band); stored with its year. */
  perFinancialYear: boolean;
  /** What the attribute means, in the ontology's own words. */
  definition: string;
  /** How onboarding asks for it; empty for a derived attribute. */
  question: string;
  /** One line under the question; may be empty. */
  help: string;
  /** The allowed values with their labels, in the ontology's order (ascending for ordered_enum). */
  options: readonly OntologyOption[];
  min: number | null;
  max: number | null;
  /** The ontology's example value, in canonical form (sets sorted, dates as YYYY-MM-DD). */
  example: unknown;
  /** Zero-based position in the ontology, the order onboarding asks in. */
  order: number;
}

export interface Ontology {
  /** The attribute set's version, which rules are written against ("0.2.0"). */
  version: string;
  wordingVersion: string;
  language: string;
  reviewStatus: string;
  /** True once an analyst has reviewed the wording (`review_status` is not needs_review). */
  wordingReviewed: boolean;
  /** The operators a rule predicate may use on each attribute type. */
  operatorsByType: Readonly<Record<string, readonly string[]>>;
  attributes: readonly OntologyAttribute[];
  /** Keys of attributes whose type, level or source this app does not know. */
  unsupported: readonly string[];
}
