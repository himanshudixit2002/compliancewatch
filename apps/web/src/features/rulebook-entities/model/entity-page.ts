import type { CanonicalEntity, MentionedClause, RuleRelation } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { markSpans, type TextSegment } from "@/shared/lib/highlight";
import { withQuery } from "@/shared/lib/url";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import { entityTypeLabel } from "./entity-type";

/**
 * One canonical entity as its page shows it: the entity, the clauses that mention it with the
 * mentions marked (the rulebook counts the spans in code points), and the relations from rule
 * versions that point at it. The clauses and the relations each come from their own read and
 * keep their own failure.
 */
export interface MentionedClauseView {
  clauseId: string;
  clauseRef: string;
  page: number | null;
  documentTitle: string;
  externalRef: string;
  publishedAt: string | null;
  segments: readonly TextSegment[];
  mentions: number;
  outOfForce: boolean;
  /** The document viewer with the first mention marked (D-037). */
  href: string;
}

export interface RelationToEntity {
  relationId: string;
  relation: string;
  from: { ruleVersionId: string; href: string; label: string | null; status: string | null };
  evidenceClauseRef: string;
  evidenceHref: string;
}

export type Part<T> = { ok: true; value: T } | { ok: false; error: ServiceErrorLike };

export interface EntityPageView {
  entity: CanonicalEntity;
  typeLabel: string;
  asOf: string | null;
  clauses: Part<readonly MentionedClauseView[]>;
  relations: Part<readonly RelationToEntity[]>;
}

function documentHref(documentId: string, query: Record<string, string | number>): string {
  return withQuery(hrefFor(screenById("admin.rulebook.document"), { documentId }), query);
}

export function mentionedClauseView(clause: MentionedClause): MentionedClauseView {
  const first = clause.mentions[0];
  return {
    clauseId: clause.clauseId,
    clauseRef: clause.clauseRef,
    page: clause.page,
    documentTitle: clause.title,
    externalRef: clause.externalRef,
    publishedAt: clause.publishedAt,
    segments: markSpans(clause.text, clause.mentions),
    mentions: clause.mentions.length,
    outOfForce: clause.outOfForce,
    href:
      first === undefined
        ? documentHref(clause.documentId, { clause_id: clause.clauseId })
        : documentHref(clause.documentId, {
            clause_id: clause.clauseId,
            start: first.start,
            end: first.end,
          }),
  };
}

export function relationToEntity(
  relation: RuleRelation,
  versions: ReadonlyMap<string, RuleVersion>,
): RelationToEntity {
  const from = versions.get(relation.fromRuleVersionId);
  return {
    relationId: relation.relationId,
    relation: relation.relation,
    from: {
      ruleVersionId: relation.fromRuleVersionId,
      href: hrefFor(screenById("admin.rulebook.version"), {
        ruleVersionId: relation.fromRuleVersionId,
      }),
      label: from === undefined ? null : `${from.ruleKey} v${from.version}`,
      status: from?.status ?? null,
    },
    evidenceClauseRef: relation.evidenceClauseRef,
    evidenceHref: documentHref(relation.evidenceDocumentId, {
      clause_id: relation.evidenceClauseId,
    }),
  };
}

export { entityTypeLabel };
