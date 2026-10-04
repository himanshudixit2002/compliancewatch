/**
 * What the citations editor (a client component) shares with the server side of the feature:
 * the rows' field names and limits, and the shape of a save's answer. It lives beside the editor
 * because a client component imports only its own directory, shared and entities.
 */
export const MAX_CITATION_ROWS = 50;
export const MAX_QUOTE_LENGTH = 400;

export type CitationPart = "clause_id" | "quote";

/** A row's field name, which is also the path a 422's `errors[].loc` gives it. */
export function citationField(index: number, part: CitationPart): string {
  return `citations.${index}.${part}`;
}

/** What a save stored, as the form shows it: the counts and each submitted quote's score. */
export interface CitationsResult {
  added: number;
  unchanged: number;
  verified: readonly {
    clauseRef: string;
    quote: string;
    verified: boolean;
    matchScore: number | null;
  }[];
}
