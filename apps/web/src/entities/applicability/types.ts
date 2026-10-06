import type { applicabilityEngine } from "@compliancewatch/contracts/openapi";

/**
 * What the applicability engine decided for a business: one rule version against one version of
 * the business's profile, with every predicate of the rule's specification, its outcome, the
 * confidence behind it and why, in words (`description` and `reason` come from the engine). A
 * change's impact groups each of the tenant's businesses with its latest decision of a version
 * under the client (the legal entity at the top of its lineage) it belongs to.
 */
type Schemas = applicabilityEngine.components["schemas"];

export type DecisionDto = Schemas["DecisionOut"];
export type DecisionPageDto = Schemas["Page_DecisionOut_"];
export type PredicateResultDto = Schemas["PredicateResultOut"];
export type ChangeImpactDto = Schemas["ChangeImpactOut"];
export type ImpactBusinessDto = Schemas["ImpactBusinessOut"];

/** applies, not_applicable or unsure: an unsure result is never a guess and needs review. */
export type Applicability = Schemas["Applicability"];
export type DecisionTrigger = Schemas["Trigger"];
export type PredicateKind = Schemas["PredicateKind"];
export type FanOutStatus = Schemas["FanOutStatus"];

export interface PredicateOutcome {
  attribute: string;
  /** structured, or free_text (which the engine never decides by itself). */
  kind: PredicateKind;
  /** The predicate in words, as the engine describes it. */
  description: string;
  outcome: Applicability;
  /** 0 to 1. */
  confidence: number;
  /** Why, in words. */
  reason: string;
  needsReview: boolean;
}

export interface Decision {
  id: string;
  businessId: string;
  ruleVersionId: string;
  result: Applicability;
  /** 0 to 1. */
  confidence: number;
  needsReview: boolean;
  profileVersion: number;
  /** The financial year the per-year attributes were read for; null when none was needed. */
  asOfFy: string | null;
  trigger: DecisionTrigger;
  decidedAt: string;
  /** Every predicate of the specification, left to right. */
  evaluated: readonly PredicateOutcome[];
}

/** One business of a client in a change's impact, with its latest decision of the version. */
export interface ImpactBusiness {
  businessId: string;
  /** entity, registration or location; null when the engine's directory does not list it. */
  level: string | null;
  decisionId: string;
  result: Applicability;
  confidence: number;
  needsReview: boolean;
  decidedAt: string;
}

export interface ImpactClient {
  /** The legal entity at the top of the businesses' lineage: a business id of /b/[businessId]. */
  entityId: string;
  businesses: readonly ImpactBusiness[];
}

/** A page of what a change means for the tenant. */
export interface ChangeImpact {
  ruleVersionId: string;
  clients: readonly ImpactClient[];
  /** Send as the cursor for the next page of clients; null on the last page. */
  nextCursor: string | null;
}
