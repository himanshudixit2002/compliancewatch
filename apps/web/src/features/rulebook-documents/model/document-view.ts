import type { Clause, RulebookDocument } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { highlightSpan, type HighlightParts } from "@/shared/lib/highlight";
import { humanise } from "@/shared/lib/humanise";
import type { HighlightRequest } from "./highlight-request";

/**
 * The document viewer's view model: the header facts, the clauses in reading order with an
 * anchor each (`#clause-en.p3`, a stable link to one clause) and their page, and what a link
 * asked to mark. A span that fits its clause is marked inside the text; one that does not (the
 * offsets run past the text) marks the whole clause and says so; a clause the document does not
 * hold, or a malformed link, marks nothing and says so. Nothing here rewrites the clause text.
 */
export type ClauseMark = "span" | "clause" | null;

export interface ClauseView {
  clauseId: string;
  clauseRef: string;
  ordinal: number;
  anchorId: string;
  page: number | null;
  text: string;
  /** Set when the span is marked: the text cut around it. */
  parts: HighlightParts | null;
  mark: ClauseMark;
}

export type HighlightOutcome =
  | { kind: "none" }
  | { kind: "span"; clauseRef: string; start: number; end: number }
  | { kind: "clause"; clauseRef: string }
  | { kind: "fallback"; clauseRef: string; start: number; end: number }
  | { kind: "missing"; clauseId: string }
  | { kind: "invalid" };

export interface HeaderItem {
  key: string;
  label: string;
  value: string;
  /** An external link for the value (the source URL). */
  href?: string;
  /** Set for identifiers: the copy button writes this. */
  copy?: string;
}

export interface DocumentView {
  documentId: string;
  title: string;
  /** The source's own reference, such as a notification number; short enough for a breadcrumb. */
  externalRef: string;
  header: HeaderItem[];
  clauses: ClauseView[];
  highlight: HighlightOutcome;
  /** The anchor of the marked clause, for scrolling to it when the link has no #fragment. */
  markedAnchorId: string | null;
}

/** "clause-en.p3": a clause reference is letters, digits, dots and dashes; anything else is dropped. */
export function clauseAnchorId(clauseRef: string): string {
  return `clause-${clauseRef.replace(/[^A-Za-z0-9._-]/g, "-")}`;
}

function headerItems(document: RulebookDocument): HeaderItem[] {
  return [
    { key: "regulator", label: t("documents.field.regulator"), value: document.regulator },
    { key: "docType", label: t("documents.field.docType"), value: humanise(document.docType) },
    { key: "externalRef", label: t("documents.field.externalRef"), value: document.externalRef },
    {
      key: "publishedAt",
      label: t("documents.field.publishedAt"),
      value:
        document.publishedAt === null
          ? t("documents.notRecorded")
          : formatDate(document.publishedAt),
    },
    {
      key: "url",
      label: t("documents.field.url"),
      value: document.url,
      href: document.url,
    },
    { key: "language", label: t("documents.field.language"), value: document.language },
    { key: "mediaType", label: t("documents.field.mediaType"), value: document.mediaType },
    {
      key: "parserVersion",
      label: t("documents.field.parserVersion"),
      value: document.parserVersion,
    },
    {
      key: "documentId",
      label: t("documents.field.documentId"),
      value: document.documentId,
      copy: document.documentId,
    },
    {
      key: "sha256",
      label: t("documents.field.sha256"),
      value: document.sha256,
      copy: document.sha256,
    },
    {
      key: "sourceId",
      label: t("documents.field.sourceId"),
      value: document.sourceId,
      copy: document.sourceId,
    },
  ];
}

function clauseView(clause: Clause, anchorId: string): ClauseView {
  return {
    clauseId: clause.clauseId,
    clauseRef: clause.clauseRef,
    ordinal: clause.ordinal,
    anchorId,
    page: clause.page,
    text: clause.text,
    parts: null,
    mark: null,
  };
}

/** Anchors unique within the document, even if two references ever came out the same. */
function anchorIds(clauses: readonly Clause[]): string[] {
  const seen = new Set<string>();
  return clauses.map((clause) => {
    let anchor = clauseAnchorId(clause.clauseRef);
    if (seen.has(anchor)) anchor = `${anchor}-${clause.ordinal}`;
    seen.add(anchor);
    return anchor;
  });
}

export function toDocumentView(
  document: RulebookDocument,
  request: HighlightRequest | "invalid" | null,
): DocumentView {
  const anchors = anchorIds(document.clauses);
  const clauses = document.clauses.map((clause, index) =>
    clauseView(clause, anchors[index] as string),
  );
  let highlight: HighlightOutcome = { kind: "none" };
  let markedAnchorId: string | null = null;
  if (request === "invalid") {
    highlight = { kind: "invalid" };
  } else if (request !== null) {
    const target = clauses.find((clause) => clause.clauseId === request.clauseId.toLowerCase());
    if (target === undefined) {
      highlight = { kind: "missing", clauseId: request.clauseId };
    } else {
      markedAnchorId = target.anchorId;
      const parts =
        request.span === undefined
          ? null
          : highlightSpan(target.text, request.span.start, request.span.end);
      if (request.span === undefined) {
        target.mark = "clause";
        highlight = { kind: "clause", clauseRef: target.clauseRef };
      } else if (parts === null) {
        target.mark = "clause";
        highlight = { kind: "fallback", clauseRef: target.clauseRef, ...request.span };
      } else {
        target.mark = "span";
        target.parts = parts;
        highlight = { kind: "span", clauseRef: target.clauseRef, ...request.span };
      }
    }
  }
  return {
    documentId: document.documentId,
    title: document.title,
    externalRef: document.externalRef,
    header: headerItems(document),
    clauses,
    highlight,
    markedAnchorId,
  };
}
