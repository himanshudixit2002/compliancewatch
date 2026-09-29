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
