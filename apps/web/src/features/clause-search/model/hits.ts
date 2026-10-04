import type { SearchHit } from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { markSpans } from "@/shared/lib/highlight";
import { withQuery } from "@/shared/lib/url";
import type { HitView, SearchResults } from "../ui/search-shared";
import { documentTypeLabel } from "./search-form";

/**
 * The search words marked in each hit. The rulebook matches word stems in its full-text leg, so
 * a word is marked where a clause word starts with it (case aside): "furnish" marks the start of
 * "furnishing". Words shorter than three letters and the commonest English words are not marked,
 * as the rulebook does not search on them either.
 */
const STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "for",
  "from",
  "in",
  "is",
  "it",
  "of",
  "on",
  "or",
  "that",
  "the",
  "this",
  "to",
  "was",
  "with",
]);

export const MIN_TERM_LENGTH = 3;

/** The words of a query worth marking, lower-cased, in order, without repeats. */
export function queryTerms(text: string): string[] {
  const words = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  return [
    ...new Set(words.filter((word) => word.length >= MIN_TERM_LENGTH && !STOP_WORDS.has(word))),
  ];
}

function escape(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The text cut into runs, the words that start with a term marked. */
export function markTerms(text: string, terms: readonly string[]) {
  const spans: { start: number; end: number }[] = [];
  for (const term of terms) {
    const pattern = new RegExp(`(?<![\\p{L}\\p{N}])${escape(term)}`, "giu");
    for (const match of text.matchAll(pattern)) {
      const start = Array.from(text.slice(0, match.index)).length;
      spans.push({ start, end: start + Array.from(match[0]).length });
    }
  }
  return markSpans(text, spans);
}

export function hitView(hit: SearchHit, index: number, terms: readonly string[]): HitView {
  return {
    clauseId: hit.clauseId,
    rank: index + 1,
    clauseRef: hit.clauseRef,
    externalRef: hit.externalRef,
    title: hit.title,
    docTypeLabel: documentTypeLabel(hit.docType),
    regulator: hit.regulator,
    publishedAt: hit.publishedAt,
    segments: markTerms(hit.text, terms),
    score: hit.score.toFixed(4),
    lexicalRank: hit.lexicalRank,
    vectorRank: hit.vectorRank,
    citedBy: hit.citedBy.map((ruleVersionId) => ({
      ruleVersionId,
      href: hrefFor(screenById("admin.rulebook.version"), { ruleVersionId }),
    })),
    outOfForce: hit.outOfForce,
    documentHref: withQuery(
      hrefFor(screenById("admin.rulebook.document"), { documentId: hit.documentId }),
      { clause_id: hit.clauseId },
    ),
  };
}

export function searchResults(text: string, hits: readonly SearchHit[]): SearchResults {
  const terms = queryTerms(text);
  return { terms, hits: hits.map((hit, index) => hitView(hit, index, terms)) };
}
