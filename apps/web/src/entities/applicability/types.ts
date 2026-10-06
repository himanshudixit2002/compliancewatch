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

/** How many businesses have each result. */
export interface ResultCounts {
  applies: number;
  notApplicable: number;
  unsure: number;
}

/** How far a version's fan-out over every tenant's businesses got, as a change's impact says. */
export interface ImpactFanOut {
  status: FanOutStatus;
  /** The directory entries of the version's level when the run began. */
  businessesTotal: number;
  evaluated: number;
  applies: number;
  startedAt: string;
  updatedAt: string;
  finishedAt: string | null;
}

/** A page of what a change means for the tenant. */
export interface ChangeImpact {
  ruleVersionId: string;
  /** Every business of the tenant with a decision of the version, whatever the page and filter. */
  counts: ResultCounts;
  /** The version's fan-out, or null when it had none. */
  fanOut: ImpactFanOut | null;
  clients: readonly ImpactClient[];
  /** Send as the cursor for the next page of clients; null on the last page. */
  nextCursor: string | null;
}

// ---- The review queue: decisions a person settles -------------------------------------------

export type ReviewItemDto = Schemas["ReviewItemOut"];
export type ReviewItemPageDto = Schemas["Page_ReviewItemOut_"];
export type ResolveDto = Schemas["ResolveIn"];
/** open, or resolved (by a reviewer, or by a later decision that needs no review). */
export type ReviewStatus = Schemas["ReviewStatus"];
/** Why a decision needs a person: a free-text predicate, or a judgement below the threshold. */
export type ReviewReason = Schemas["ReviewReason"];
/** applies or not_applicable append a decision; dismiss closes the item and appends nothing. */
export type Resolution = Schemas["Resolution"];

/** A decision waiting for a reviewer, or settled, of one tenant. */
export interface ReviewItem {
  id: string;
  businessId: string;
  ruleVersionId: string;
  reason: ReviewReason;
  status: ReviewStatus;
  openedAt: string;
  /** The decision under review: the latest of the business and version while the item is open. */
  decision: Decision;
  resolution: Resolution | null;
  /** The reviewer; null when a later decision that needs no review settled the item. */
  resolvedBy: string | null;
  resolvedAt: string | null;
  /** The reviewer's note; empty while open. */
  note: string;
  /** The decision a resolution to applies or not_applicable appended. */
  resolutionDecisionId: string | null;
}

export interface ReviewItemPage {
  items: readonly ReviewItem[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

/** What a reviewer settles an item with; the reviewer is the session's user, never a field. */
export interface ResolveInput {
  resolution: Resolution;
  note: string;
}

// ---- Fan-outs and the global hold ----------------------------------------------------------

export type FanOutRunDto = Schemas["FanOutRunOut"];
export type FanOutRunPageDto = Schemas["Page_FanOutRunOut_"];
export type FanOutHoldDto = Schemas["FanOutHoldOut"];
export type FanOutHoldInDto = Schemas["FanOutHoldIn"];
export type FanOutReasonDto = Schemas["FanOutReasonIn"];
export type FanOutResumeDto = Schemas["FanOutResumeIn"];
export type AttributeLevel = Schemas["AttributeLevel"];
export type RuleVersionStatus = Schemas["RuleVersionStatus"];

/** One published rule version decided for every business of its level, batch by batch. */
export interface FanOutRun {
  ruleVersionId: string;
  ruleKey: string;
  level: AttributeLevel;
  status: FanOutStatus;
  triggerEventId: string;
  /** The versions it supersedes, whose decisions each business is compared with. */
  supersedes: readonly string[];
  /** The directory entries of the level when the run began. */
  businessesTotal: number;
  evaluated: number;
  applies: number;
  /** Businesses compared with the superseded version, and those whose result changed. */
  flipsCompared: number;
  flips: number;
  /** flips over flipsCompared; null before any comparison. */
  flipRate: number | null;
  startedAt: string;
  updatedAt: string;
  finishedAt: string | null;
  /** Why and by whom the status last changed: a user id, system:... or service:<client>. */
  statusReason: string;
  statusBy: string;
  /** Why a failed run failed; empty otherwise. */
  lastError: string;
}

export interface FanOutRunPage {
  items: readonly FanOutRun[];
  /** Send as the cursor for the next page; null on the last page. */
  nextCursor: string | null;
}

/** The global hold: while it is set, no fan-out starts its next batch. */
export interface FanOutHold {
  held: boolean;
  reason: string | null;
  /** A user id, system:applicability-engine or service:<client>. */
  setBy: string | null;
  setAt: string | null;
}

// ---- Dry runs: what a version or a specification would decide --------------------------------

export type DryRunInDto = Schemas["DryRunIn"];
export type DryRunOutDto = Schemas["DryRunOut"];
export type DryRunSampleDto = Schemas["DryRunSampleOut"];

/** A dry run's subject (a rule version, or a specification) and its scope. */
export interface DryRunRequest {
  ruleVersionId: string | null;
  /** The kernel's predicate tree mapping, when no version holds the specification yet. */
  specification: Readonly<Record<string, unknown>> | null;
  /** The version's own level when null; required with a specification. */
  level: AttributeLevel | null;
  /** One tenant's businesses; every tenant's when null. */
  tenantId: string | null;
  /** Decisions to keep as samples, 0 to 50. */
  sampleSize: number;
}

/** The businesses whose result one attribute decided, by result. */
export interface AttributeCounts extends ResultCounts {
  attribute: string;
}

/** One business as the dry run decided it; nothing of it is stored. */
export interface DryRunSample {
  tenantId: string;
  businessId: string;
  profileVersion: number;
  result: Applicability;
  confidence: number;
  needsReview: boolean;
  /** The attributes whose predicates decided the result. */
  deciding: readonly string[];
  evaluated: readonly PredicateOutcome[];
}

/** What the version or specification would decide for the businesses in scope. */
export interface DryRunReport {
  ruleVersionId: string | null;
  ruleKey: string | null;
  status: RuleVersionStatus | null;
  level: AttributeLevel;
  tenantId: string | null;
  /** The financial year the per-year attributes were read for (the current one in India). */
  asOfFy: string;
  businessesTotal: number;
  evaluated: number;
  /** Businesses the profile service no longer has. */
  skipped: number;
  counts: ResultCounts;
  needsReview: number;
  byAttribute: readonly AttributeCounts[];
  samples: readonly DryRunSample[];
  /** The most businesses a dry run evaluates. */
  maxBusinesses: number;
  ranAt: string;
}
