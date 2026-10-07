import type { ClauseDetail, RuleRelation } from "@/entities/rulebook/types";
import type { Citation, RuleVersion, WorkflowStep } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { withQuery } from "@/shared/lib/url";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import type { SpecLine } from "@/shared/ui/specification";
import type { AccessView } from "../ui/workflow-shared";
import { versionHref } from "./version-list";

/**
 * The version page as the views need it: the version, its condition in words, its citations
 * with the clauses they cite, its relations either way, and what the workflow panel may offer.
 * Each part that comes from its own read carries its own failure, so one failed read leaves the
 * rest of the page in place.
 */
export interface QuoteMark {
  before: string;
  mark: string;
  after: string;
}

export interface CitationView {
  citation: Citation;
  /** The cited clause with its document's facts, or null when its read failed. */
  clause: ClauseDetail | null;
  /** The document viewer, with the clause marked. */
  clauseHref: string;
  /** The quote marked inside the clause's text when it appears there word for word. */
  quoteMark: QuoteMark | null;
}

export interface VersionRef {
  ruleVersionId: string;
  href: string;
  /** "rule_key v2" when the version was read, else null (the id is shown). */
  label: string | null;
  status: string | null;
}

export interface RelationView {
  relationId: string;
  relation: string;
  /** The version at the other end, for a relation between versions. */
  version: VersionRef | null;
  /** The entity at the other end: its type, canonical name and page. */
  entity: { entityType: string; name: string; href: string | null } | null;
  evidenceClauseRef: string;
  evidenceHref: string;
  periodLabel: string | null;
  newDueOn: string | null;
}

export type Part<T> = { ok: true; value: T } | { ok: false; error: ServiceErrorLike };

export interface VersionPageView {
  version: RuleVersion;
  /** The condition in words, or null when the version states none yet. */
  specification: SpecLine | null;
  /** Set when the ontology could not be read and the values are shown as stored. */
  ontologyError: ServiceErrorLike | null;
  citations: Part<readonly CitationView[]>;
  relations: Part<{ from: readonly RelationView[]; to: readonly RelationView[] }>;
  steps: readonly WorkflowStep[];
  access: AccessView;
  /** Citations change only while the version is a draft. */
  canCite: boolean;
  graphHref: string;
}

/** The document viewer with one clause marked (D-037). */
export function clauseHref(documentId: string, clauseId: string): string {
  return withQuery(hrefFor(screenById("admin.rulebook.document"), { documentId }), {
    clause_id: clauseId,
  });
}

/** The quote inside the clause text when it is there word for word (a verified quote may not be). */
export function markQuote(text: string, quote: string): QuoteMark | null {
  const at = quote === "" ? -1 : text.indexOf(quote);
  if (at < 0) return null;
  return {
    before: text.slice(0, at),
    mark: text.slice(at, at + quote.length),
    after: text.slice(at + quote.length),
  };
}

export function citationView(citation: Citation, clause: ClauseDetail | null): CitationView {
  return {
    citation,
    clause,
    clauseHref: clauseHref(citation.documentId, citation.clauseId),
    quoteMark: clause === null ? null : markQuote(clause.text, citation.quote),
  };
}

export function versionRef(ruleVersionId: string, read: RuleVersion | undefined): VersionRef {
  return {
    ruleVersionId,
    href: versionHref(ruleVersionId),
    label: read === undefined ? null : `${read.ruleKey} v${read.version}`,
    status: read?.status ?? null,
  };
}

export function entityHref(entityId: string): string {
  return hrefFor(screenById("admin.rulebook.canonical.entity"), { entityId });
}

/**
 * A relation as one of the page's lists shows it: `direction` says which end is the other one
 * (the target for a relation from this version, the source for one to it).
 */
export function relationView(
  relation: RuleRelation,
  direction: "from" | "to",
  versions: ReadonlyMap<string, RuleVersion>,
): RelationView {
  const otherVersionId =
    direction === "from" ? relation.toRuleVersionId : relation.fromRuleVersionId;
  const toEntity = direction === "from" && relation.toKind !== "rule_version";
  return {
    relationId: relation.relationId,
    relation: relation.relation,
    version:
      otherVersionId === null || toEntity
        ? null
        : versionRef(otherVersionId, versions.get(otherVersionId)),
    entity: toEntity
      ? {
          entityType: relation.toKind,
          name: relation.toRef,
          href: relation.toEntityId === null ? null : entityHref(relation.toEntityId),
        }
      : null,
    evidenceClauseRef: relation.evidenceClauseRef,
    evidenceHref: clauseHref(relation.evidenceDocumentId, relation.evidenceClauseId),
    periodLabel: relation.periodLabel,
    newDueOn: relation.newDueOn,
  };
}

/** The relations graph centred on this version. */
export function graphHref(ruleVersionId: string): string {
  return withQuery(hrefFor(screenById("admin.rulebook.relations.graph")), {
    rule_version_id: ruleVersionId,
  });
}
