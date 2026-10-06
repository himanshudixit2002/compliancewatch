import type { Answer, Question } from "@/entities/answer/types";
import type { Business } from "@/entities/business/types";
import type { RulebookDocument } from "@/entities/rulebook/types";
import type { Result } from "@/server/result";

/**
 * What the ask screen needs: the public API's ask for the session's tenant, the business the
 * question is about (its nodes), and the documents the answer cites, for their clauses' text.
 */
export interface AskPort {
  ask(question: Question): Promise<Result<Answer>>;
  business(businessId: string): Promise<Result<Business>>;
  document(documentId: string): Promise<Result<RulebookDocument>>;
}
