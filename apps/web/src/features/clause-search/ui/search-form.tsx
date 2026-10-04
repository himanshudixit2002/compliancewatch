"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef } from "react";
import {
  Badge,
  Button,
  Checkbox,
  DateField,
  EmptyState,
  ErrorState,
  Field,
  HighlightMark,
  Input,
  Label,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import { formatDate } from "@/shared/lib/dates";
import {
  DEFAULT_HITS,
  REGULATOR_MAX_LENGTH,
  SEARCH_FIELDS,
  TEXT_MAX_LENGTH,
  type HitView,
  type SearchResults,
  type SearchValues,
} from "./search-shared";

export type SearchAction = (
  state: ActionState<SearchResults>,
  formData: FormData,
) => Promise<ActionState<SearchResults>>;

export interface SearchFormProps {
  action: SearchAction;
  docTypes: readonly { value: string; label: string }[];
  counts: readonly { value: string; label: string }[];
}

interface Attempt {
  state: ActionState<SearchResults>;
  values: SearchValues;
  count: number;
}

const EMPTY: SearchValues = {
  text: "",
  regulator: "",
  docTypes: [],
  asOf: "",
  k: String(DEFAULT_HITS),
};

function rankText(rank: number | null): string {
  return rank === null ? t("search.hit.notInLeg") : String(rank);
}

function Hit({ hit }: { hit: HitView }) {
  return (
    <li
      data-slot="search-hit"
      data-clause={hit.clauseId}
      data-clause-ref={hit.clauseRef}
      className="flex flex-col gap-2 rounded-md border border-line p-4"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-sm font-medium text-fg">
          {t("search.hit.heading", {
            rank: hit.rank,
            ref: hit.clauseRef,
            document: hit.externalRef,
          })}
        </span>
        {hit.outOfForce ? <Badge tone="warning">{t("search.hit.outOfForce")}</Badge> : null}
      </div>
      <p className="text-xs text-fg-muted">
        {t("search.hit.document", {
          title: hit.title,
          type: hit.docTypeLabel,
          regulator: hit.regulator,
          date: hit.publishedAt === null ? t("search.hit.undated") : formatDate(hit.publishedAt),
        })}
      </p>
      <p className="text-sm whitespace-pre-wrap text-fg">
        {hit.segments.map((segment, index) =>
          segment.mark ? (
            <HighlightMark
              key={index}
              startLabel={t("search.markStart")}
              endLabel={t("search.markEnd")}
            >
              {segment.text}
            </HighlightMark>
          ) : (
            <span key={index}>{segment.text}</span>
          ),
        )}
      </p>
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]" data-slot="ranks">
        <dt className="text-fg-muted">{t("search.hit.score")}</dt>
        <dd data-rank="score">{hit.score}</dd>
        <dt className="text-fg-muted">{t("search.hit.lexical")}</dt>
        <dd data-rank="lexical">{rankText(hit.lexicalRank)}</dd>
        <dt className="text-fg-muted">{t("search.hit.vector")}</dt>
        <dd data-rank="vector">{rankText(hit.vectorRank)}</dd>
        <dt className="text-fg-muted">{t("search.hit.citedBy")}</dt>
        <dd>
          {hit.citedBy.length === 0 ? (
            t("search.hit.notCited")
          ) : (
            <ul className="flex flex-wrap gap-2">
              {hit.citedBy.map((version) => (
                <li key={version.ruleVersionId}>
                  <Link
                    href={version.href as Route}
                    className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                  >
                    {version.ruleVersionId}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
      <Link
        href={hit.documentHref as Route}
        className="text-sm text-primary underline-offset-2 hover:underline"
      >
        {t("search.hit.open", { ref: hit.clauseRef })}
      </Link>
    </li>
  );
}

/**
 * The clause search: the words (and optionally a regulator, document types, a date and how many
 * hits) are posted to the action and the hits listed from its answer, each with its rank in the
 * full-text leg and in the vector leg and the fused score, the words marked. A refusal keeps
 * what was typed and puts each problem on its field.
 */
export function SearchForm({ action, docTypes, counts }: SearchFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: {
        text: String(formData.get(SEARCH_FIELDS.text) ?? ""),
        regulator: String(formData.get(SEARCH_FIELDS.regulator) ?? ""),
        docTypes: formData.getAll(SEARCH_FIELDS.docType).map(String),
        asOf: String(formData.get(SEARCH_FIELDS.asOf) ?? ""),
        k: String(formData.get(SEARCH_FIELDS.k) ?? DEFAULT_HITS),
      },
      count: previous.count + 1,
    }),
    { state: idleAction<SearchResults>(), values: EMPTY, count: 0 },
  );
  const { state, values } = attempt;
  const resultRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (attempt.count === 0) return;
    if (attempt.state.status === "error" && attempt.state.problem === undefined) {
      textRef.current?.focus();
    } else {
      resultRef.current?.focus();
    }
  }, [attempt]);

  const problem = state.status === "error" ? state.problem : undefined;
  const results = state.status === "ok" ? state.value : undefined;

  return (
    <div data-slot="clause-search" className="flex flex-col gap-6">
      <form
        key={attempt.count}
        action={formAction}
        noValidate
        aria-label={t("search.form.label")}
        className="flex max-w-3xl flex-col gap-4"
      >
        <Field
          id={`${id}-text`}
          label={t("search.form.text")}
          description={t("search.form.textHelp")}
          error={fieldErrorOf(state, SEARCH_FIELDS.text)}
          required
        >
          <Textarea
            ref={textRef}
            name={SEARCH_FIELDS.text}
            defaultValue={values.text}
            maxLength={TEXT_MAX_LENGTH}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            id={`${id}-regulator`}
            label={t("search.form.regulator")}
            error={fieldErrorOf(state, SEARCH_FIELDS.regulator)}
          >
            <Input
              name={SEARCH_FIELDS.regulator}
              defaultValue={values.regulator}
              maxLength={REGULATOR_MAX_LENGTH}
              autoComplete="off"
            />
          </Field>
          <DateField
            id={`${id}-as-of`}
            name={SEARCH_FIELDS.asOf}
            label={t("search.form.asOf")}
            description={t("search.form.asOfHelp")}
            defaultValue={values.asOf}
            error={fieldErrorOf(state, SEARCH_FIELDS.asOf)}
          />
          <Field
            id={`${id}-k`}
            label={t("search.form.count")}
            error={fieldErrorOf(state, SEARCH_FIELDS.k)}
          >
            <Select name={SEARCH_FIELDS.k} defaultValue={values.k} options={counts} />
          </Field>
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-fg">{t("search.form.docTypes")}</legend>
          <div className="flex flex-wrap gap-4">
            {docTypes.map((option) => (
              <div key={option.value} className="flex items-center gap-2">
                <Checkbox
                  id={`${id}-type-${option.value}`}
                  name={SEARCH_FIELDS.docType}
                  value={option.value}
                  defaultChecked={values.docTypes.includes(option.value)}
                />
                <Label htmlFor={`${id}-type-${option.value}`}>{option.label}</Label>
              </div>
            ))}
          </div>
          {fieldErrorOf(state, SEARCH_FIELDS.docType) === undefined ? null : (
            <p className="text-sm text-danger">{fieldErrorOf(state, SEARCH_FIELDS.docType)}</p>
          )}
        </fieldset>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("search.form.pending") : t("search.form.submit")}
          </Button>
        </div>
      </form>
      <div ref={resultRef} tabIndex={-1} className="flex flex-col gap-4 outline-none">
        {problem === undefined ? null : (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        )}
        {results === undefined ? null : (
          <section aria-labelledby={`${id}-results`} className="flex flex-col gap-3">
            <h2 id={`${id}-results`} className="text-lg font-semibold text-fg">
              {t("search.results.heading")}
            </h2>
            <p role="status" className="text-sm text-fg-muted" data-slot="search-summary">
              {t("search.results.count", { count: results.hits.length })}
            </p>
            {results.hits.length === 0 ? (
              <EmptyState
                heading="h3"
                title={t("search.results.emptyTitle")}
                body={t("search.results.emptyBody")}
              />
            ) : (
              <ol className="flex flex-col gap-3" data-slot="search-hits">
                {results.hits.map((hit) => (
                  <Hit key={hit.clauseId} hit={hit} />
                ))}
              </ol>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
