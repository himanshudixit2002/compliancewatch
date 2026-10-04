import type { CitationInput, CitationReport } from "@/entities/rule-version/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import {
  MAX_CITATION_ROWS,
  MAX_QUOTE_LENGTH,
  citationField,
  type CitationsResult,
} from "../ui/citations-shared";

/**
 * The citations form: rows of a clause id and the words of that clause the rule rests on. The
 * rulebook stores all of them or none: every quote must be in its clause (a close match, with no
 * number, form code or month name the clause lacks), and a clause it does not hold refuses the
 * whole request. The shape is checked here first; the verification is the rulebook's.
 */
export type ParsedCitations =
  | { ok: true; citations: CitationInput[] }
  | { ok: false; fieldErrors: FieldErrors; formErrors: string[] };

/**
 * The rows the form posted, in order. Rows are numbered from 0 without gaps; a row with neither
 * part is skipped, and one with a single part is refused on the part it lacks.
 */
export function parseCitationsForm(formData: FormData): ParsedCitations {
  const fieldErrors: Record<string, string[]> = {};
  const citations: CitationInput[] = [];
  for (let index = 0; index < MAX_CITATION_ROWS; index += 1) {
    const clauseRaw = formData.get(citationField(index, "clause_id"));
    const quoteRaw = formData.get(citationField(index, "quote"));
    if (clauseRaw === null && quoteRaw === null) break;
    const clauseId = String(clauseRaw ?? "")
      .trim()
      .toLowerCase();
    const quote = String(quoteRaw ?? "").trim();
    if (clauseId === "" && quote === "") continue;
    if (!isHexUuid(clauseId)) {
      fieldErrors[citationField(index, "clause_id")] = [
        clauseId === "" ? t("citations.form.clauseRequired") : t("citations.form.clauseMalformed"),
      ];
    }
    if (quote === "") {
      fieldErrors[citationField(index, "quote")] = [t("citations.form.quoteRequired")];
    } else if (quote.length > MAX_QUOTE_LENGTH) {
      fieldErrors[citationField(index, "quote")] = [
        t("citations.form.quoteTooLong", { max: MAX_QUOTE_LENGTH }),
      ];
    }
    citations.push({ clauseId, quote });
  }
  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors, formErrors: [] };
  if (citations.length === 0) {
    return { ok: false, fieldErrors: {}, formErrors: [t("citations.form.noneGiven")] };
  }
  return { ok: true, citations };
}

/** The problem slugs the citation route answers for a quote not in its clause and an unknown clause. */
export const NOT_VERIFIED = "rulebook-citation-not-verified";
export const CLAUSE_NOT_STORED = "rulebook-clause-not-found";

/**
 * The quotes the rulebook refused, one line each, from its problem detail
 * ("2 quotes are not in their clause: en.p3 of <document>: score 0.42, missing 2026; ...").
 * The rulebook lists up to five; an unexpected detail gives no lines, and is shown whole.
 */
export function quoteFailures(detail: string | undefined): string[] {
  if (detail === undefined) return [];
  const colon = detail.indexOf(": ");
  if (colon < 0) return [];
  return detail
    .slice(colon + 2)
    .split("; ")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** The clause ids the rulebook does not hold, from its detail ("2 clauses are not stored: a, b"). */
export function unknownClauses(detail: string | undefined): string[] {
  if (detail === undefined) return [];
  const colon = detail.indexOf(": ");
  if (colon < 0) return [];
  return detail
    .slice(colon + 2)
    .split(", ")
    .map((id) => id.trim().toLowerCase())
    .filter((id) => isHexUuid(id));
}

/**
 * The rows a refused quote belongs to. A failure line starts "<clause ref> of <document id>:"
 * and the rulebook lists them in the order of the rows, but without the quote, so a line is put
 * on a row only when every row citing that clause failed (as many lines as rows): two rows on
 * one clause with one failure leave the failure on the list alone rather than on the wrong row.
 */
export function failuresByRow(
  failures: readonly string[],
  rows: readonly { clauseRef: string; documentId: string }[],
): Record<number, string> {
  const found: Record<number, string> = {};
  const prefixes = new Set(
    rows
      .filter((row) => row.clauseRef !== "")
      .map((row) => `${row.clauseRef} of ${row.documentId}: `),
  );
  for (const prefix of prefixes) {
    const lines = failures.filter((failure) => failure.startsWith(prefix));
    const indexes = rows.flatMap((row, index) =>
      `${row.clauseRef} of ${row.documentId}: ` === prefix ? [index] : [],
    );
    if (lines.length !== indexes.length) continue;
    indexes.forEach((index, position) => {
      found[index] = (lines[position] as string).slice(prefix.length);
    });
  }
  return found;
}

/** What a save stored, as the form shows it: the counts and each submitted quote's score. */
export function citationsResult(
  report: CitationReport,
  sent: readonly CitationInput[],
): CitationsResult {
  const verified = sent.flatMap((input) => {
    const stored = report.citations.find(
      (citation) => citation.clauseId === input.clauseId && citation.quote === input.quote,
    );
    return stored === undefined
      ? []
      : [
          {
            clauseRef: stored.clauseRef,
            quote: stored.quote,
            verified: stored.verified,
            matchScore: stored.matchScore,
          },
        ];
  });
  return { added: report.added, unchanged: report.unchanged, verified };
}
