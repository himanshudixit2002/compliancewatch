import type { Business as BusinessEntity } from "@/entities/business/types";
import type { RulebookDocument } from "@/entities/rulebook/types";

/** The business a question is about, with its registrations. */
export type Business = Pick<BusinessEntity, "id" | "name" | "pan" | "registrations">;

/** What the ask screen reads of a cited document: its facts and its clauses. */
export type RulebookDocumentLike = Pick<
  RulebookDocument,
  "documentId" | "title" | "externalRef" | "url" | "clauses"
>;
