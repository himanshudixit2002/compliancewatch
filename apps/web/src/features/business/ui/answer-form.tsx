"use client";

import type { ReactNode } from "react";
import { useActionState, useEffect, useRef } from "react";
import { Banner, ErrorState } from "@compliancewatch/ui";
import type { OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";
import { AnswerButtons } from "./answer-buttons";
import { AttributeControl } from "./attribute-control";

export type AnswerAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface AnswerFormProps {
  action: AnswerAction;
  attribute: OntologyAttribute;
  /** Prefix for the element ids; unique on the page. */
  id: string;
  /** The control's label: the question, or the attribute's name. */
  label: ReactNode;
  /** Keeps the label for screen readers only, when a heading already asks the question. */
  hideLabel?: boolean;
  description?: ReactNode;
  /** The hidden fields the action needs: business, node, attribute and year. */
  hidden: Readonly<Record<string, string>>;
  /** The form field the control submits under. */
  valueField: string;
  defaultValue?: string | readonly string[];
  /** Leaves out Not sure and Does not apply. */
  valueOnly?: boolean;
}

interface Attempt {
  state: ActionState;
  values: string[] | undefined;
  count: number;
}

/**
 * One attribute's answer: the control the ontology type calls for, the hidden fields naming
 * where it is stored, and the three answer buttons. The action either moves the page on (the
 * questions step redirects to the next question) or returns a message for the status line. A
 * refused answer keeps what was chosen (the control remounts from the submitted values), shows
 * the message under the control and the service's problem above it, and moves focus to the
 * summary.
 */
export function AnswerForm({
  action,
  attribute,
  id,
  label,
  hideLabel,
  description,
  hidden,
  valueField,
  defaultValue,
  valueOnly,
}: AnswerFormProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: formData.getAll(valueField).map(String),
      count: previous.count + 1,
    }),
    { state: idleAction(), values: undefined, count: 0 },
  );
  const { state } = attempt;
  const alertRef = useRef<HTMLDivElement>(null);
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const valueError = fieldErrorOf(state, valueField);

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") alertRef.current?.focus();
  }, [attempt]);

  const initial =
    state.status === "error" && attempt.values !== undefined ? attempt.values : defaultValue;

  return (
    <form action={formAction} data-slot="answer-form" className="flex flex-col gap-4">
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {state.status === "error" ? (
        <div
          ref={alertRef}
          tabIndex={-1}
          data-slot="answer-errors"
          className="flex flex-col gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
        >
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
            />
          ) : null}
          {formErrors.length > 0 || !problem ? (
            <Banner tone="danger" title={t("answer.refused")}>
              {formErrors.length > 0 ? (
                <ul>
                  {formErrors.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              ) : (
                t("answer.checkValue")
              )}
            </Banner>
          ) : null}
        </div>
      ) : null}
      <AttributeControl
        key={attempt.count}
        attribute={attribute}
        id={id}
        name={valueField}
        label={label}
        hideLabel={hideLabel}
        description={description}
        defaultValue={initial}
        error={valueError}
        disabled={pending}
      />
      <AnswerButtons id={id} pending={pending} valueOnly={valueOnly} />
      {state.status === "ok" && state.message ? (
        <p role="status" data-slot="answer-saved" className="text-sm text-fg">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
