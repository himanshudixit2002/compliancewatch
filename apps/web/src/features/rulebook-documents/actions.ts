"use server";

import { redirect } from "next/navigation";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { documentsGateway } from "./gateway";
import { OPEN_FIELDS, parseOpenForm } from "./model/open-form";

/**
 * Opens a document by id: the tool's gate again, the id's shape (the id, or the document's
 * sha256), then the rulebook's read, so an id the rulebook does not hold is answered on the form
 * instead of on a not-found page. On success it moves to the viewer; the read it made is cached
 * under the document's tag, so the viewer does not fetch the document twice.
 */
export async function openDocument(_state: ActionState, formData: FormData): Promise<ActionState> {
  await requireScreenSession(screenById("admin.rulebook.documents"));
  const parsed = parseOpenForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const found = await documentsGateway().document(parsed.documentId);
  if (!found.ok) {
    if (found.error.kind === "not_found") {
      return fieldFailure({ [OPEN_FIELDS.documentId]: [t("documents.open.notFound")] });
    }
    return toActionState(found);
  }
  redirect(hrefFor(screenById("admin.rulebook.document"), { documentId: parsed.documentId }));
}
