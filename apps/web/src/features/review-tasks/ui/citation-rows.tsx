"use client";

import { useRef, useState } from "react";
import { Button, Field, Select, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { useClauseTexts } from "./clause-texts";
import { LIMITS, citationField, type ClauseOption } from "./form-shared";

export interface CitationRowsProps {
  idPrefix: string;
  options: readonly ClauseOption[];
  errors: Readonly<Record<string, readonly string[]>>;
  disabled: boolean;
  /** What the rows are for, as the group's legend. */
  legend: string;
  description: string;
}

interface Row {
  key: number;
  clauseId: string;
  quote: string;
}

/**
 * Citations to add, one row each: a clause of a document the draft rests on, then the words of
 * it the rule rests on, typed or pasted. The rulebook verifies every quote against its clause; the
 * row says beforehand whether the clause holds the quote word for word (the clause's text from the
 * page's `ClauseTextsProvider`), which the rulebook's match score does not need (spacing and
 * punctuation may differ).
 */
export function CitationRows({
  idPrefix,
  options,
  errors,
  disabled,
  legend,
  description,
}: CitationRowsProps) {
  const next = useRef(0);
  const [rows, setRows] = useState<Row[]>([]);
  const texts = useClauseTexts();
  const add = () => {
    const key = next.current;
    next.current += 1;
    setRows((current) => [...current, { key, clauseId: "", quote: "" }]);
  };
  const update = (key: number, change: Partial<Row>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  const remove = (key: number) => setRows((current) => current.filter((row) => row.key !== key));

  return (
    <fieldset className="flex flex-col gap-3" data-slot="citation-rows">
      <legend className="text-sm font-semibold text-fg">{legend}</legend>
      <p className="max-w-prose text-sm text-fg-muted">{description}</p>
      {options.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("workbench.citations.noClauses")}</p>
      ) : null}
      {rows.map((row, index) => {
        const clauseName = citationField(index, "clause_id");
        const quoteName = citationField(index, "quote");
        const clause = options.find((option) => option.value === row.clauseId);
        const text = clause === undefined ? undefined : texts[clause.value];
        const quote = row.quote.trim();
        const found = text !== undefined && quote !== "" && text.includes(quote);
        return (
          <div
            key={row.key}
            className="flex flex-col gap-2 rounded-md border bg-surface-raised p-3"
            data-slot="citation-row"
          >
            <Field
              id={`${idPrefix}-citation-${row.key}-clause`}
              label={t("workbench.citations.clause", { n: index + 1 })}
              error={errors[clauseName]}
              required
            >
              <Select
                name={clauseName}
                value={row.clauseId}
                placeholder={t("workbench.citations.choose")}
                disabled={disabled || options.length === 0}
                onChange={(event) => update(row.key, { clauseId: event.target.value })}
                options={options.map((option) => ({ value: option.value, label: option.label }))}
              />
            </Field>
            <Field
              id={`${idPrefix}-citation-${row.key}-quote`}
              label={t("workbench.citations.quote", { n: index + 1 })}
              description={
                text === undefined || quote === ""
                  ? t("workbench.citations.quoteHelp", { max: LIMITS.quote })
                  : found
                    ? t("workbench.citations.found")
                    : t("workbench.citations.notFound")
              }
              error={errors[quoteName]}
              required
            >
              <Textarea
                name={quoteName}
                value={row.quote}
                rows={2}
                maxLength={LIMITS.quote}
                disabled={disabled}
                onChange={(event) => update(row.key, { quote: event.target.value })}
              />
            </Field>
            <div>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={disabled}
                onClick={() => remove(row.key)}
                aria-label={t("workbench.citations.removeNamed", { n: index + 1 })}
              >
                {t("workbench.citations.remove")}
              </Button>
            </div>
          </div>
        );
      })}
      <div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={disabled || options.length === 0 || rows.length >= LIMITS.citations}
          onClick={add}
        >
          {t("workbench.citations.add")}
        </Button>
      </div>
    </fieldset>
  );
}
