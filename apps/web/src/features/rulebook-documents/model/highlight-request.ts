import { isHexUuid } from "@/shared/lib/identifiers";

/**
 * What a link into the viewer asks to mark: `?clause_id=<uuid>` for a whole clause (a relation's
 * evidence clause), or `?clause_id=<uuid>&start=<n>&end=<n>` for a span inside it (a mention),
 * with offsets in code points, end exclusive, as the rulebook stores them. Anything malformed is
 * "invalid", so the page can say the link was broken instead of silently marking nothing.
 */
export type SearchParams = Readonly<Record<string, string | readonly string[] | undefined>>;

export interface HighlightRequest {
  clauseId: string;
  /** Absent: the whole clause is asked for. */
  span?: { start: number; end: number };
}

export const HIGHLIGHT_PARAMS = { clauseId: "clause_id", start: "start", end: "end" } as const;

const OFFSET = /^\d{1,7}$/;

function single(params: SearchParams, name: string): string | undefined {
  const value = params[name];
  if (value === undefined) return undefined;
  return typeof value === "string" ? value : "";
}

export function parseHighlightRequest(params: SearchParams): HighlightRequest | "invalid" | null {
  const clauseId = single(params, HIGHLIGHT_PARAMS.clauseId);
  const start = single(params, HIGHLIGHT_PARAMS.start);
  const end = single(params, HIGHLIGHT_PARAMS.end);
  if (clauseId === undefined && start === undefined && end === undefined) return null;
  if (clauseId === undefined || !isHexUuid(clauseId)) return "invalid";
  if (start === undefined && end === undefined) return { clauseId: clauseId.toLowerCase() };
  if (start === undefined || end === undefined || !OFFSET.test(start) || !OFFSET.test(end)) {
    return "invalid";
  }
  return { clauseId: clauseId.toLowerCase(), span: { start: Number(start), end: Number(end) } };
}
