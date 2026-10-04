import { DOCUMENT_TYPES, type DocumentType, type SearchQuery } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import {
  DEFAULT_HITS,
  HIT_COUNTS,
  REGULATOR_MAX_LENGTH,
  SEARCH_FIELDS,
  TEXT_MAX_LENGTH,
  type SearchValues,
} from "../ui/search-shared";

/** A document type as people read it ("press_release" is "Press release"). */
export function documentTypeLabel(docType: string): string {
  return humanise(docType);
}

export function documentTypeOptions(): { value: DocumentType; label: string }[] {
  return DOCUMENT_TYPES.map((value) => ({ value, label: documentTypeLabel(value) }));
}

export function hitCountOptions(): { value: string; label: string }[] {
  return HIT_COUNTS.map((count) => ({ value: String(count), label: String(count) }));
}

function isDocumentType(value: string): value is DocumentType {
  return (DOCUMENT_TYPES as readonly string[]).includes(value);
}

export type ParsedSearch =
  | { ok: true; query: SearchQuery; values: SearchValues }
  | { ok: false; fieldErrors: FieldErrors; values: SearchValues };

/** The posted form: the words, and optionally a regulator, document types, a date and a count. */
export function parseSearchForm(formData: FormData): ParsedSearch {
  const text = String(formData.get(SEARCH_FIELDS.text) ?? "").trim();
  const regulator = String(formData.get(SEARCH_FIELDS.regulator) ?? "").trim();
  const docTypes = formData.getAll(SEARCH_FIELDS.docType).map(String);
  const asOf = String(formData.get(SEARCH_FIELDS.asOf) ?? "").trim();
  const kText = String(formData.get(SEARCH_FIELDS.k) ?? "").trim();
  const values: SearchValues = { text, regulator, docTypes, asOf, k: kText };
  const fieldErrors: Record<string, string[]> = {};
  if (text === "") fieldErrors[SEARCH_FIELDS.text] = [t("search.form.textRequired")];
  else if (text.length > TEXT_MAX_LENGTH) {
    fieldErrors[SEARCH_FIELDS.text] = [t("search.form.textTooLong", { max: TEXT_MAX_LENGTH })];
  }
  if (regulator.length > REGULATOR_MAX_LENGTH) {
    fieldErrors[SEARCH_FIELDS.regulator] = [
      t("search.form.regulatorTooLong", { max: REGULATOR_MAX_LENGTH }),
    ];
  }
  if (!docTypes.every(isDocumentType)) {
    fieldErrors[SEARCH_FIELDS.docType] = [t("search.form.docTypeUnknown")];
  }
  if (asOf !== "" && !isDateKey(asOf))
    fieldErrors[SEARCH_FIELDS.asOf] = [t("ruleVersions.asOfInvalid")];
  const k = kText === "" ? DEFAULT_HITS : Number(kText);
  if (!(HIT_COUNTS as readonly number[]).includes(k)) {
    fieldErrors[SEARCH_FIELDS.k] = [t("search.form.countUnknown")];
  }
  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors, values };
  return {
    ok: true,
    values,
    query: {
      text,
      docTypes: docTypes.filter(isDocumentType),
      k,
      ...(regulator === "" ? {} : { regulator }),
      ...(asOf === "" ? {} : { asOf }),
    },
  };
}
