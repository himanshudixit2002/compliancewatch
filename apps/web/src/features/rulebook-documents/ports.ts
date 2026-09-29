import type { RulebookDocument } from "@/entities/rulebook/types";
import type { Result } from "@/server/result";

/** What the document tools need: one document with its clauses, by id. */
export interface DocumentsPort {
  document(documentId: string): Promise<Result<RulebookDocument>>;
}
