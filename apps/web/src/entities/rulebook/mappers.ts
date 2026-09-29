import type { Clause, ClauseDto, RulebookDocument, RulebookDocumentDto } from "./types";

export function clauseFromDto(dto: ClauseDto): Clause {
  return {
    clauseId: dto.clause_id,
    clauseRef: dto.clause_ref,
    ordinal: dto.ordinal,
    page: dto.page ?? null,
    text: dto.text,
  };
}

/** The document with its clauses sorted by ordinal, whatever order they arrived in. */
export function documentFromDto(dto: RulebookDocumentDto): RulebookDocument {
  return {
    documentId: dto.document_id,
    sourceId: dto.source_id,
    sha256: dto.sha256,
    regulator: dto.regulator,
    docType: dto.doc_type,
    externalRef: dto.external_ref,
    url: dto.url,
    title: dto.title,
    language: dto.language,
    mediaType: dto.media_type,
    parserVersion: dto.parser_version,
    publishedAt: dto.published_at ?? null,
    clauses: dto.clauses.map(clauseFromDto).sort((a, b) => a.ordinal - b.ordinal),
  };
}
