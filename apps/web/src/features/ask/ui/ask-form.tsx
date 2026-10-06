"use client";

import { useActionState, useEffect, useId, useRef, useState } from "react";
import { Badge, Button, ErrorState, Field, Select, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction, type ActionState } from "@/shared/lib/action-state";
import { CitationList } from "@/shared/ui/citation-list";
import { ASK_FIELDS, QUESTION_MAX_LENGTH, type AnswerView } from "./answer-shared";

export type AskAction = (
  state: ActionState<AnswerView>,
  formData: FormData,
) => Promise<ActionState<AnswerView>>;

export interface AskFormProps {
  action: AskAction;
  businessId: string;
  nodes: readonly { id: string; label: string }[];
}

interface Asked {
  state: ActionState<AnswerView>;
  /** What was sent, so a refused question stays in its field after React resets the form. */
  question: string;
  node: string;
  count: number;
}

function AnswerPanel({ answer }: { answer: AnswerView }) {
  return (
    <div data-slot="answer" data-outcome={answer.outcome} className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold text-fg">{t("ask.answer.heading")}</h2>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={answer.tone}>{answer.outcomeLabel}</Badge>
        <span className="text-sm text-fg-muted" data-slot="answer-layer">
          {answer.layerLabel}
        </span>
      </div>
      <p className="text-sm text-fg-muted">
        {t("ask.answer.about", {
          question: answer.question,
          about: answer.about,
          date: answer.asOf,
        })}
      </p>
      <p className="max-w-prose text-base whitespace-pre-wrap text-fg" data-slot="answer-text">
        {answer.text}
      </p>
      {answer.reason === null ? null : (
        <p className="text-sm text-fg-muted" data-slot="answer-reason">
          {t("ask.answer.reason", { reason: answer.reason })}
        </p>
      )}
      <section aria-labelledby="answer-citations" className="flex flex-col gap-2">
        <h3 id="answer-citations" className="text-base font-semibold text-fg">
          {t("ask.answer.citations")}
        </h3>
        <CitationList citations={answer.citations} empty={t("ask.answer.noCitations")} />
      </section>
      <details className="text-sm">
        <summary className="cursor-pointer text-primary">{t("ask.answer.layers")}</summary>
        <ul className="mt-2 flex flex-col gap-1" data-slot="answer-layers">
          {answer.layers.map((run, index) => (
            <li key={`${run.layer}-${index}`}>
              {run.reason === null
                ? t("ask.answer.layerRun", { layer: run.label, result: run.result })
                : t("ask.answer.layerRunReason", {
                    layer: run.label,
                    result: run.result,
                    reason: run.reason,
                  })}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/**
 * A question about the business, answered by the public API's ask: the question and the node it
 * is about (a registration for its returns) go in the POST body, and the answer comes back with
 * the layer that decided, its citations with each clause's text and source, or the honest
 * "not covered" sentence with why. A refusal keeps the question in its field.
 */
export function AskForm({ action, businessId, nodes }: AskFormProps) {
  const id = useId();
  const [asked, dispatch, pending] = useActionState(
    async (previous: Asked, formData: FormData): Promise<Asked> => {
      const state = await action(idleAction(), formData);
      return {
        state,
        question: String(formData.get(ASK_FIELDS.question) ?? ""),
        node: String(formData.get(ASK_FIELDS.node) ?? ""),
        count: previous.count + 1,
      };
    },
    { state: idleAction(), question: "", node: nodes[0]?.id ?? "", count: 0 },
  );
  const [question, setQuestion] = useState("");
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (asked.count > 0) outcomeRef.current?.focus();
  }, [asked]);
  const { state } = asked;
  const fieldError = (name: string) =>
    state.status === "error" ? state.fieldErrors?.[name]?.[0] : undefined;
  return (
    <div className="flex flex-col gap-6" data-slot="ask">
      <form action={dispatch} aria-label={t("ask.form")} className="flex flex-col gap-4">
        <input type="hidden" name={ASK_FIELDS.businessId} value={businessId} />
        <Field
          id={`${id}-question`}
          label={t("ask.question.label")}
          description={t("ask.question.help", { max: QUESTION_MAX_LENGTH })}
          error={fieldError(ASK_FIELDS.question)}
        >
          <Textarea
            name={ASK_FIELDS.question}
            rows={3}
            maxLength={QUESTION_MAX_LENGTH}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </Field>
        <Field
          id={`${id}-node`}
          label={t("ask.node.label")}
          description={t("ask.node.help")}
          error={fieldError(ASK_FIELDS.node)}
          className="max-w-xl"
        >
          <Select
            key={asked.count}
            name={ASK_FIELDS.node}
            defaultValue={asked.node}
            options={nodes.map((node) => ({ value: node.id, label: node.label }))}
          />
        </Field>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("ask.asking") : t("ask.submit")}
          </Button>
        </div>
      </form>
      <div
        ref={outcomeRef}
        tabIndex={-1}
        role="region"
        aria-label={t("ask.answer.label")}
        className="flex flex-col gap-3 outline-none"
        data-slot="ask-outcome"
      >
        {state.status === "ok" && state.value !== undefined ? (
          <AnswerPanel answer={state.value} />
        ) : state.status === "error" ? (
          <>
            {state.problem === undefined ? null : (
              <ErrorState
                title={state.problem.title}
                detail={state.problem.detail}
                correlationId={state.problem.correlationId || undefined}
              />
            )}
            {(state.formErrors ?? []).map((message, index) => (
              <p key={index} className="text-sm text-danger">
                {message}
              </p>
            ))}
          </>
        ) : null}
      </div>
    </div>
  );
}
