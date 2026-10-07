import type { DocumentDetail } from "@/entities/pipeline/types";
import type { RulebookDocument } from "@/entities/rulebook/types";
import type { Citation, TaskDocument } from "@/entities/rule-version/types";
import type { ApiError, Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { markSpans, quoteSpan, type TextSegment } from "@/shared/lib/highlight";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import type { ClauseRun } from "../ui/clause-texts";
import { percent } from "./queue";

/**
 * The source pane: each document the draft rests on, as the rulebook stores it (its clauses in
 * reading order, each cited quote marked where its clause holds it word for word), the file the
 * pipeline stored for it, and every citation with its verification. A quote its clause does not
 * hold word for word (the rulebook verifies by a match score, so spacing or punctuation may
 * differ) marks the whole clause and says that the span did not match, as the document viewer
 * does. The file opens in a new tab through the stored-file handler and is never framed here: the
 * app answers every page with `X-Frame-Options: DENY` (D-062).
 */
export interface QuoteRef {
  clauseId: string;
  quote: string;
}

export interface SourceClause {
  clauseId: string;
  clauseRef: string;
  anchorId: string;
  page: number | null;
  /**
   * The text in runs by code point, the quotes found word for word marked; the text itself is in
   * `SourcePane.clauseTexts`, sent once for the pane and the forms alike.
   */
  runs: ClauseRun[];
  /** A quote did not match word for word, so the whole clause is marked. */
  wholeMarked: boolean;
  /** The quotes of this clause that did not match word for word. */
  unmatched: string[];
  /** How many quotes cite the clause. */
  quotes: number;
}

export type SourceFile =
  | { kind: "stored"; href: string; type: string; size: string }
  | { kind: "none" }
  | { kind: "error"; error: ServiceErrorLike };

export interface SourceDocument {
  documentId: string;
  title: string;
  externalRef: string;
  facts: string;
  /** Why the document is here: the candidate came from it, or the draft cites it. */
  role: "candidate" | "cited";
  viewerHref: string;
  file: SourceFile;
  clauses: SourceClause[] | null;
  clausesError: ServiceErrorLike | null;
}

export interface CitationRow {
  citationId: string;
  clauseRef: string;
  quote: string;
  verified: boolean;
  /** "97%", or null before it was checked. */
  score: string | null;
  verifiedAt: string | null;
  /** The clause in this pane, when its document's clauses are shown. */
  anchorHref: string | null;
  /** The clause marked in the document viewer. */
  viewerHref: string;
}

export interface SourcePane {
  documents: SourceDocument[];
  citations: CitationRow[];
  /** The text of every clause shown, by clause id. */
  clauseTexts: Record<string, string>;
}

/** An anchor unique within the page: the document and the clause reference. */
export function sourceAnchorId(documentId: string, clauseRef: string): string {
  return `source-${documentId.slice(0, 8)}-${clauseRef.replace(/[^A-Za-z0-9._-]/g, "-")}`;
}

const CONTENT_LABELS: Readonly<Record<string, string>> = {
  "application/pdf": "PDF",
  "text/html": "HTML",
};

function sizeText(bytes: number): string {
  if (bytes < 1000) return t("workbench.file.bytes", { count: bytes });
  if (bytes < 1_000_000)
    return t("workbench.file.kilobytes", { count: Math.round(bytes / 100) / 10 });
  return t("workbench.file.megabytes", { count: Math.round(bytes / 100_000) / 10 });
}

function errorLike(error: ApiError): ServiceErrorLike {
  return {
    message: error.message,
    status: error.status,
    requestId: error.requestId,
    problem: { detail: error.problem?.detail ?? null },
  };
}

/** The pipeline's record of the file: stored, never stored (a 404), or a read that failed. */
export function sourceFile(
  documentId: string,
  stored: Result<DocumentDetail> | undefined,
): SourceFile {
  if (stored === undefined) return { kind: "none" };
  if (!stored.ok) {
    return stored.error.kind === "not_found"
      ? { kind: "none" }
      : { kind: "error", error: errorLike(stored.error) };
  }
  const base = (stored.value.contentType.split(";")[0] ?? "").trim().toLowerCase();
  return {
    kind: "stored",
    href: hrefFor(screenById("system.raw-document"), { documentId }),
    type: CONTENT_LABELS[base] ?? base,
    size: sizeText(stored.value.size),
  };
}

/** Contiguous runs of text as code point ranges, in reading order. */
function runsOf(segments: readonly TextSegment[]): ClauseRun[] {
  const runs: ClauseRun[] = [];
  let start = 0;
  for (const segment of segments) {
    const end = start + Array.from(segment.text).length;
    runs.push({ start, end, mark: segment.mark });
    start = end;
  }
  return runs;
}

function clauseView(
  documentId: string,
  clause: RulebookDocument["clauses"][number],
  quotes: readonly string[],
): SourceClause {
  const spans: { start: number; end: number }[] = [];
  const unmatched: string[] = [];
  for (const quote of quotes) {
    const span = quoteSpan(clause.text, quote);
    if (span === null) unmatched.push(quote);
    else spans.push(span);
  }
  const wholeMarked = unmatched.length > 0;
  return {
    clauseId: clause.clauseId,
    clauseRef: clause.clauseRef,
    anchorId: sourceAnchorId(documentId, clause.clauseRef),
    page: clause.page,
    runs: runsOf(wholeMarked ? [{ text: clause.text, mark: true }] : markSpans(clause.text, spans)),
    wholeMarked,
    unmatched,
    quotes: quotes.length,
  };
}

function factsOf(facts: TaskDocument | null, document: RulebookDocument | null): string {
  const regulator = facts?.regulator ?? document?.regulator ?? "";
  const type = facts?.docType ?? document?.docType ?? "";
  const published = facts?.publishedAt ?? document?.publishedAt ?? null;
  return [
    regulator,
    type === "" ? "" : humanise(type),
    published === null ? t("workbench.source.noDate") : formatDate(published),
  ]
    .filter((part) => part !== "")
    .join(", ");
}

/**
 * The pane from the documents in order (the candidate's first), their reads and the quotes:
 * every citation of the draft and, for a candidate task, the quotes its candidate proposes.
 */
export function sourcePane(input: {
  documentIds: readonly string[];
  candidateDocumentId: string | null;
  facts: ReadonlyMap<string, TaskDocument>;
  documents: ReadonlyMap<string, Result<RulebookDocument>>;
  stored: ReadonlyMap<string, Result<DocumentDetail>>;
  quotes: readonly QuoteRef[];
  citations: readonly Citation[];
}): SourcePane {
  const byClause = new Map<string, string[]>();
  for (const { clauseId, quote } of input.quotes) {
    const list = byClause.get(clauseId) ?? [];
    if (!list.includes(quote)) list.push(quote);
    byClause.set(clauseId, list);
  }
  const anchors = new Map<string, string>();
  const clauseTexts: Record<string, string> = {};
  const documents = input.documentIds.map((documentId): SourceDocument => {
    const read = input.documents.get(documentId);
    const document = read?.ok === true ? read.value : null;
    for (const clause of document?.clauses ?? []) clauseTexts[clause.clauseId] = clause.text;
    const facts = input.facts.get(documentId) ?? null;
    const clauses =
      document === null
        ? null
        : document.clauses.map((clause) =>
            clauseView(documentId, clause, byClause.get(clause.clauseId) ?? []),
          );
    for (const clause of clauses ?? []) anchors.set(clause.clauseId, clause.anchorId);
    return {
      documentId,
      title: document?.title ?? facts?.title ?? documentId,
      externalRef: document?.externalRef ?? facts?.externalRef ?? "",
      facts: factsOf(facts, document),
      role: documentId === input.candidateDocumentId ? "candidate" : "cited",
      viewerHref: hrefFor(screenById("admin.rulebook.document"), { documentId }),
      file: sourceFile(documentId, input.stored.get(documentId)),
      clauses,
      clausesError: read === undefined || read.ok ? null : errorLike(read.error),
    };
  });
  return {
    documents,
    clauseTexts,
    citations: input.citations.map((citation) => {
      const anchor = anchors.get(citation.clauseId);
      return {
        citationId: citation.citationId,
        clauseRef: citation.clauseRef,
        quote: citation.quote,
        verified: citation.verified,
        score: citation.matchScore === null ? null : percent(citation.matchScore),
        verifiedAt: citation.verifiedAt === null ? null : formatDateTime(citation.verifiedAt),
        anchorHref: anchor === undefined ? null : `#${anchor}`,
        viewerHref: clauseInViewer(citation.documentId, citation.clauseId),
      };
    }),
  };
}

/** The document viewer with one clause marked, for a citation whose document is not shown. */
export function clauseInViewer(documentId: string, clauseId: string): string {
  return withQuery(hrefFor(screenById("admin.rulebook.document"), { documentId }), {
    clause_id: clauseId,
  });
}
