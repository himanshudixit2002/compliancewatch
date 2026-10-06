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

// ---- The knowledge graph and the clause index (open reads) -------------------------------------

export type ResolutionStatus = Schemas["ResolutionStatus"];
export type EntityDto = Schemas["EntityOut"];
export type EntityResolutionDto = Schemas["EntityResolutionOut"];
export type MentionedClauseDto = Schemas["MentionedClauseOut"];
export type RelationDto = Schemas["RelationOut"];
export type ClauseDetailDto = Schemas["ClauseDetailOut"];
export type SearchInDto = Schemas["SearchIn"];
export type SearchHitDto = Schemas["SearchHitOut"];

/** domain_kernel.knowledge.EntityType: the ten kinds of entity the knowledge tables hold. */
export const ENTITY_TYPES = [
  "notification",
  "circular",
  "section",
  "rule",
  "form",
  "hsn_code",
  "sac_code",
  "tax_rate",
  "threshold",
  "state",
] as const satisfies readonly EntityType[];

/** How a name resolves (`GET /v1/rulebook/entities/resolve`), in the spec's order. */
export const RESOLUTION_STATUSES = [
  "resolved",
  "ambiguous",
  "not_found",
  "unqualified",
  "empty",
] as const satisfies readonly ResolutionStatus[];

/** domain_kernel.documents.DocumentType: what a regulator document is. */
export const DOCUMENT_TYPES = [
  "notification",
  "circular",
  "press_release",
  "act_amendment",
  "statute",
] as const satisfies readonly DocumentType[];

/** The kinds a relation has (domain_kernel.knowledge.RelationKind), in the spec's order. */
export const RELATION_KINDS = [
  "supersedes",
  "amends",
  "refers_to",
  "exempts",
  "extends_deadline",
  "corrects",
  "withdraws",
] as const satisfies readonly RelationKind[];

/** The problem slug the entity routes answer for an id the rulebook does not hold. */
export const ENTITY_NOT_FOUND = "rulebook-entity-not-found";

/** An entity an analyst aligned: one canonical name and the normalised names it also goes by. */
export interface CanonicalEntity {
  entityId: string;
  entityType: EntityType;
  canonicalName: string;
  aliases: readonly string[];
}

/** A name resolved the way alignment resolves a mention (the kernel's normalisation first). */
export interface EntityResolution {
  status: ResolutionStatus;
  entityType: EntityType;
  name: string;
  normalised: string;
  /** Set when the status is resolved. */
  entity: CanonicalEntity | null;
  /** The entities sharing the alias, when the status is ambiguous. */
  candidates: readonly CanonicalEntity[];
}

/** Where a mention sits in its clause, in code points (start inclusive, end exclusive). */
export interface MentionSpan {
  text: string;
  start: number;
  end: number;
}

/** A clause with its document's facts, as the clause and the search routes return it. */
export interface ClauseDetail {
  clauseId: string;
  documentId: string;
  clauseRef: string;
  ordinal: number;
  page: number | null;
  text: string;
  regulator: string;
  docType: DocumentType;
  externalRef: string;
  title: string;
  url: string;
  language: string;
  publishedAt: string | null;
}

/** A clause that mentions an entity, with the spans and whether its rule is out of force. */
export interface MentionedClause extends ClauseDetail {
  mentions: readonly MentionSpan[];
  outOfForce: boolean;
}

/**
 * A relation from a rule version to another version or to an entity (ADR-017), with its
 * evidence clause; a deadline extension carries the period and the new due date.
 */
export interface RuleRelation {
  relationId: string;
  fromRuleVersionId: string;
  relation: RelationKind;
  /** "rule_version", or the entity type the relation points at. */
  toKind: string;
  /** The target version's id, or the entity's canonical name. */
  toRef: string;
  toRuleVersionId: string | null;
  toEntityId: string | null;
  evidenceClauseId: string;
  evidenceClauseRef: string;
  evidenceDocumentId: string;
  candidateId: string | null;
  periodLabel: string | null;
  newDueOn: string | null;
}

/** What a clause search asks: the text, and optionally a regulator, document types and a date. */
export interface SearchQuery {
  text: string;
  regulator?: string;
  docTypes: readonly DocumentType[];
  asOf?: string;
  k: number;
}

/** One hit of the hybrid search, with each leg's rank and the fused score. */
export interface SearchHit {
  clauseId: string;
  documentId: string;
  clauseRef: string;
  text: string;
  regulator: string;
  docType: DocumentType;
  externalRef: string;
  title: string;
  publishedAt: string | null;
  /** Reciprocal rank fusion over the two legs. */
  score: number;
  /** 1-based rank in the full-text leg, or null when that leg did not find the clause. */
  lexicalRank: number | null;
  /** 1-based rank in the vector leg, or null when that leg did not run or find it. */
  vectorRank: number | null;
  /** Published or superseded versions citing the clause with a verified quote. */
  citedBy: readonly string[];
  outOfForce: boolean;
}
