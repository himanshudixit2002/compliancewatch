import type { rulebook } from "@compliancewatch/contracts/openapi";

/**
 * Rulebook documents as the rulebook service stores them: one parsed source document (a
 * notification, a circular) with its clauses in reading order. The records are regulatory text
 * shared by every tenant; the web app shows them exactly as stored and never rewrites them.
 * Clause spans elsewhere (a mention, a quote) count code points into `Clause.text`.
 */
type Schemas = rulebook.components["schemas"];

export type RulebookDocumentDto = Schemas["DocumentOut"];
export type ClauseDto = Schemas["ClauseOut"];
export type DocumentType = Schemas["DocumentType"];

/** The problem slug the document route answers for an id it does not hold. */
export const DOCUMENT_NOT_FOUND = "rulebook-document-not-found";

export interface Clause {
  clauseId: string;
  /** The parser's reference, such as "en.p3" (language, paragraph); unique within a document. */
  clauseRef: string;
  ordinal: number;
  /** The page of the source file the clause starts on, when the parser recorded one. */
  page: number | null;
  text: string;
}

export interface RulebookDocument {
  documentId: string;
  sourceId: string;
  sha256: string;
  regulator: string;
  docType: DocumentType;
  externalRef: string;
  url: string;
  title: string;
  language: string;
  mediaType: string;
  parserVersion: string;
  /** ISO date, or null when the source gave none. */
  publishedAt: string | null;
  /** In reading order (by ordinal). */
  clauses: Clause[];
}

// ---- Review decisions (the analyst's side; the review token's routes) -------------------------

export type EntityType = Schemas["EntityType"];
export type MentionDecision = Schemas["MentionDecision"];
export type EntityRejectReason = Schemas["EntityRejectReason"];
export type CandidateRejectReason = Schemas["CandidateRejectReason"];
export type RelationKind = Schemas["RelationKind"];
export type CandidateStatus = Schemas["CandidateStatus"];

export type EntityDecisionInDto = Schemas["DecisionIn"];
export type EntityDecisionOutDto = Schemas["GroupDecisionOut"];
export type ApproveInDto = Schemas["ApproveIn"];
export type ApprovalOutDto = Schemas["ApprovalOut"];
export type RejectInDto = Schemas["RejectIn"];
export type RelationCandidateDto = Schemas["RelationCandidateOut"];

/**
 * One decision over every open mention of an (entity type, proposed name) group, or over the
 * items named in `reviewIds`. Who decided is not part of it: the server layer fills
 * `decided_by` from the session, so a form cannot name somebody else.
 */
export interface EntityGroupDecision {
  entityType: EntityType;
  proposedName: string;
  decision: MentionDecision;
  /** add_alias: the entity the name joins. */
  entityId?: string;
  /** reject: why. */
  rejectReason?: EntityRejectReason;
  /** The mentions covered; absent for the whole group. */
  reviewIds?: readonly string[];
  note: string;
}

export interface EntityGroupDecided {
  status: string;
  resolution: string | null;
  entityId: string | null;
  itemsClosed: number;
  relationTargetsUpdated: number;
}

/** Approving a relation candidate into a rule relation from a draft rule version. */
export interface CandidateApproval {
  fromRuleVersionId: string;
  /** The affected version, for the kinds that target one. */
  targetRuleVersionId?: string;
  note: string;
}

export interface CandidateApproved {
  candidateId: string;
  ruleRelationId: string;
}

export interface CandidateRejection {
  reason: CandidateRejectReason;
  note: string;
}

export interface RelationCandidate {
  candidateId: string;
  documentId: string;
  relation: RelationKind;
  targetType: EntityType;
  targetName: string;
  targetEntityId: string | null;
  targetRuleKey: string | null;
  evidenceClauseId: string;
  evidenceQuote: string;
  quoteScore: number;
  periodLabel: string | null;
  newDueOn: string | null;
  promptVersion: string;
  model: string;
  confidence: number;
  issues: { code: string; detail: string }[];
  needsReview: boolean;
  status: string;
  rejectReason: string | null;
  decidedBy: string;
}
