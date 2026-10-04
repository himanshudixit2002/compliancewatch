"use client";

import { useActionState, useEffect, useId, useRef, useState } from "react";
import { Button, ErrorState, Field, Input, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import {
  MAX_CITATION_ROWS,
  MAX_QUOTE_LENGTH,
  citationField,
  type CitationsResult,
} from "./citations-shared";

export type SaveCitationsAction = (
  state: ActionState<CitationsResult>,
  formData: FormData,
) => Promise<ActionState<CitationsResult>>;

export interface CitationsEditorProps {
  /** The save action, bound to the version. */
  action: SaveCitationsAction;
}

interface Row {
  key: number;
  clauseId: string;
  quote: string;
}

interface Attempt {
  state: ActionState<CitationsResult>;
  count: number;
  /** Saves that went through; the rows start over after each. */
  saves: number;
}

interface RowsFormProps {
  formAction: (formData: FormData) => void;
  state: ActionState<CitationsResult>;
  pending: boolean;
}

/** The rows themselves, kept until a save goes through (the editor remounts them then). */
function RowsForm({ formAction, state, pending }: RowsFormProps) {
  const id = useId();
  const nextKey = useRef(1);
  const [rows, setRows] = useState<Row[]>([{ key: 0, clauseId: "", quote: "" }]);

  const update = (key: number, change: Partial<Omit<Row, "key">>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  const remove = (key: number) => {
    const fresh = nextKey.current++;
    setRows((current) =>
      current.length === 1
        ? [{ key: fresh, clauseId: "", quote: "" }]
        : current.filter((row) => row.key !== key),
    );
  };
  const add = () => {
    const fresh = nextKey.current++;
    setRows((current) =>
      current.length >= MAX_CITATION_ROWS
        ? current
        : [...current, { key: fresh, clauseId: "", quote: "" }],
    );
  };

  return (
    <form
      action={formAction}
      noValidate
      aria-label={t("citations.form.label")}
      className="flex flex-col gap-4"
    >
      <ol className="flex flex-col gap-4">
        {rows.map((row, index) => {
          const clauseName = citationField(index, "clause_id");
          const quoteName = citationField(index, "quote");
          return (
            <li
              key={row.key}
              data-slot="citation-row"
              className="flex flex-col gap-3 rounded-md border border-line p-3"
            >
              <p className="text-sm font-medium text-fg">
                {t("citations.form.row", { number: index + 1 })}
              </p>
              <Field
                id={`${id}-clause-${row.key}`}
                label={t("citations.form.clause")}
                description={t("citations.form.clauseHelp")}
                error={fieldErrorOf(state, clauseName)}
                required
              >
                <Input
                  name={clauseName}
                  value={row.clauseId}
                  onChange={(event) => update(row.key, { clauseId: event.target.value })}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono"
                />
              </Field>
              <Field
                id={`${id}-quote-${row.key}`}
                label={t("citations.form.quote")}
                description={t("citations.form.quoteHelp", { max: MAX_QUOTE_LENGTH })}
                error={fieldErrorOf(state, quoteName)}
                required
              >
                <Textarea
                  name={quoteName}
                  value={row.quote}
                  maxLength={MAX_QUOTE_LENGTH}
                  onChange={(event) => update(row.key, { quote: event.target.value })}
                />
              </Field>
              <div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => remove(row.key)}
                  disabled={pending}
                >
                  {t("citations.form.remove", { number: index + 1 })}
                </Button>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          variant="secondary"
          onClick={add}
          disabled={pending || rows.length >= MAX_CITATION_ROWS}
        >
          {t("citations.form.add")}
        </Button>
        <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
          {pending ? t("citations.form.pending") : t("citations.form.submit")}
        </Button>
      </div>
    </form>
  );
}

/**
 * Cites clauses for a draft version: rows of a clause id and the quote the rule rests on, added
 * and removed here and sent together. The rulebook stores every row or none; a refusal keeps the
 * rows, puts each problem on its row (a clause it does not hold, a quote it could not find in its
 * clause) and lists every failure it gave; a save says what was stored and starts the rows over.
 */
export function CitationsEditor({ action }: CitationsEditorProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const state = await action(previous.state, formData);
      return {
        state,
        count: previous.count + 1,
        saves: previous.saves + (state.status === "ok" ? 1 : 0),
      };
    },
    { state: idleAction<CitationsResult>(), count: 0, saves: 0 },
  );
  const resultRef = useRef<HTMLDivElement>(null);
  const { state } = attempt;

  useEffect(() => {
    if (attempt.count > 0) resultRef.current?.focus();
  }, [attempt]);

  const problem = state.status === "error" ? state.problem : undefined;
  const failures = state.status === "error" ? (state.formErrors ?? []) : [];

  return (
    <div data-slot="citations-editor" className="flex flex-col gap-4">
      <RowsForm key={attempt.saves} formAction={formAction} state={state} pending={pending} />
      <div ref={resultRef} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        <div role="status" data-slot="citations-result">
          {state.status === "ok" ? (
            <div className="flex flex-col gap-1 text-sm text-fg">
              <p>{state.message}</p>
              {state.value === undefined || state.value.verified.length === 0 ? null : (
                <ul className="flex flex-col gap-1" data-slot="citations-verified">
                  {state.value.verified.map((item, index) => (
                    <li key={index}>
                      {t("citations.verifiedLine", {
                        ref: item.clauseRef,
                        score: item.matchScore === null ? "-" : item.matchScore.toFixed(2),
                      })}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
        {problem === undefined ? null : (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        )}
        {failures.length === 0 ? null : (
          <div data-slot="citations-failures" className="flex flex-col gap-1">
            <p className="text-sm font-medium text-fg">
              {problem === undefined ? t("citations.form.fix") : t("citations.failuresLead")}
            </p>
            <ul className="ml-5 list-disc text-sm text-fg">
              {failures.map((failure, index) => (
                <li key={index}>{failure}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
