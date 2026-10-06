/**
 * What the dry run form and its server action share, in the ui directory so the client form may
 * import it: the field names (the request's JSON paths, so a 422's `errors[].loc` lands on its
 * field), the limits the engine applies (checked again in the action), the values the form keeps
 * across a submit, and the report the action answers with, already worded for the page.
 */
export const DRY_RUN_FIELDS = {
  subject: "subject",
  ruleVersionId: "rule_version_id",
  specification: "specification",
  level: "scope.level",
  tenantId: "scope.tenant_id",
  sampleSize: "scope.sample_size",
} as const;

export type DryRunSubject = "version" | "specification";

export type LevelChoice = "" | "entity" | "registration" | "location";

/** The decisions a dry run keeps as samples, at most, and by default. */
export const MAX_SAMPLES = 50;
export const DEFAULT_SAMPLES = 10;

/** The longest specification the form sends, in characters of JSON. */
export const SPECIFICATION_MAX_LENGTH = 20000;

export interface DryRunFormValues {
  subject: DryRunSubject;
  ruleVersionId: string;
  specification: string;
  level: LevelChoice;
  tenantId: string;
  sampleSize: string;
}

export interface CountView {
  key: "applies" | "not_applicable" | "unsure" | "needs_review";
  label: string;
  value: string;
  /** "40% of those decided"; null when nothing was decided. */
  share: string | null;
}

export interface AttributeRowView {
  attribute: string;
  /** The ontology's meaning of the attribute; null when the ontology does not hold it. */
  definition: string | null;
  applies: string;
  notApplicable: string;
  unsure: string;
}

export interface SampleRowView {
  businessId: string;
  tenantId: string;
  result: "applies" | "not_applicable" | "unsure";
  needsReview: boolean;
  confidence: string;
  /** The attributes whose conditions decided the result. */
  deciding: readonly string[];
  conditions: readonly {
    attribute: string;
    description: string;
    outcome: "applies" | "not_applicable" | "unsure";
    reason: string;
  }[];
}

/** A dry run's report as the page shows it. */
export interface DryRunReportView {
  /** "example_rule (draft)", or that it was a specification. */
  subject: string;
  scope: string;
  level: string;
  year: string;
  ranAt: string;
  /** True when the directory listed no business in scope, so nothing was decided. */
  nothingInScope: boolean;
  facts: {
    inScope: string;
    evaluated: string;
    skipped: string;
    max: string;
  };
  counts: readonly CountView[];
  byAttribute: readonly AttributeRowView[];
  samples: readonly SampleRowView[];
}

/** What a dry run answered: the values it was asked with and its report. */
export interface DryRunAnswer {
  values: DryRunFormValues;
  report: DryRunReportView;
}

/** The engine's refusal of a scope wider than its maximum (CW_APPLICABILITY_DRY_RUN_MAX). */
export const TOO_LARGE = "applicability-dry-run-too-large";
