/**
 * What the search form (a client component) shares with the server side of the feature: the
 * field names and limits, and the shape of the results the action answers with. It lives beside
 * the form because a client component imports only its own directory, shared and entities.
 */
export const SEARCH_FIELDS = {
  text: "text",
  regulator: "regulator",
  docType: "doc_type",
  asOf: "as_of",
  k: "k",
} as const;

/** The rulebook takes 1 to 2000 characters of text and 1 to 50 hits. */
export const TEXT_MAX_LENGTH = 2000;
export const REGULATOR_MAX_LENGTH = 40;
export const HIT_COUNTS = [8, 20, 50] as const;
export const DEFAULT_HITS = 8;

export interface SearchValues {
  text: string;
  regulator: string;
  docTypes: readonly string[];
  asOf: string;
  k: string;
}

export interface HitSegment {
  text: string;
  mark: boolean;
}

/** One hit as the results list shows it, ranks and score as the rulebook returned them. */
export interface HitView {
  clauseId: string;
  rank: number;
  clauseRef: string;
  externalRef: string;
  title: string;
  docTypeLabel: string;
  regulator: string;
  publishedAt: string | null;
  segments: readonly HitSegment[];
  score: string;
  lexicalRank: number | null;
  vectorRank: number | null;
  citedBy: readonly { ruleVersionId: string; href: string }[];
  outOfForce: boolean;
  /** The document viewer with the clause marked. */
  documentHref: string;
}

export interface SearchResults {
  hits: readonly HitView[];
  /** The words marked in the hits. */
  terms: readonly string[];
}
