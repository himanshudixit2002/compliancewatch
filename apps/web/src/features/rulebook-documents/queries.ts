import "server-only";

import type { ClientContext } from "@/server/api/services";
import { mapResult, type Result } from "@/server/result";
import { documentsGateway } from "./gateway";
import type { HighlightRequest } from "./model/highlight-request";
import { toDocumentView, type DocumentView } from "./model/document-view";

/** The viewer's read: the document with its clauses, and what the link asked to mark. */
export async function getDocumentView(
  documentId: string,
  request: HighlightRequest | "invalid" | null,
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<Result<DocumentView>> {
  const document = await documentsGateway({ fetchImpl: deps.fetchImpl }).document(documentId);
  return mapResult(document, (value) => toDocumentView(value, request));
}
