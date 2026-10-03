import { t } from "@/shared/i18n";
import { documentIdFrom } from "@/shared/lib/identifiers";
import type { FieldErrors } from "@/shared/lib/action-state";

/** The one field of the "open a document" form. */
export const OPEN_FIELDS = { documentId: "document_id" } as const;

export type OpenFormResult =
  { ok: true; documentId: string } | { ok: false; fieldErrors: FieldErrors };

/** The document id from the form: the id itself, or the sha256 it is cut from. */
export function parseOpenForm(formData: FormData): OpenFormResult {
  const raw = formData.get(OPEN_FIELDS.documentId);
  const value = typeof raw === "string" ? raw : "";
  if (value.trim() === "") {
    return { ok: false, fieldErrors: { [OPEN_FIELDS.documentId]: [t("documents.open.required")] } };
  }
  const documentId = documentIdFrom(value);
  if (documentId === null) {
    return {
      ok: false,
      fieldErrors: { [OPEN_FIELDS.documentId]: [t("documents.open.malformed")] },
    };
  }
  return { ok: true, documentId };
}
