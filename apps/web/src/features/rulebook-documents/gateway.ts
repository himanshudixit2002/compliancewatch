import "server-only";

import { documentFromDto } from "@/entities/rulebook/mappers";
import type { RulebookDocument } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { cachedRead, tags } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { DocumentsPort } from "./ports";

/**
 * Rulebook documents over the typed rulebook client, with no tenant header (the records are
 * shared by every tenant). A document never changes under its id (the rulebook refuses to store
 * other clauses under an id it holds), so a read is kept for five minutes under the document's
 * own tag; only a 200 is kept, so an id the pipeline registers later is found on the next visit.
 */
export class DocumentsGateway implements DocumentsPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async document(documentId: string): Promise<Result<RulebookDocument>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        ...cachedRead([tags.rulebook.document(documentId)]),
      }),
    );
    return mapBody(result, documentFromDto);
  }
}

/** The gateway for a page or an action; tests add fetchImpl. */
export function documentsGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): DocumentsGateway {
  return new DocumentsGateway(ctx);
}
