"use client";

import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { useActionState, useEffect, useRef } from "react";
import { Banner, Button, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";
import { PrefillPanel, type PrefillPanelResult } from "./prefill-panel";

/** The action's result as the form needs it (the business model's BusinessStepResult). */
export interface BusinessFormResult extends PrefillPanelResult {
  businessId: string;
  nextHref: string;
  complete: boolean;
}

export type BusinessAction = (
  state: ActionState<BusinessFormResult>,
  formData: FormData,
) => Promise<ActionState<BusinessFormResult>>;

export interface BusinessFormProps {
  action: BusinessAction;
  /** The hidden Idempotency-Key input the page rendered for this form. */
  idempotencyInput: ReactNode;
  fields: { gstin: string; name: string; registrationName: string };
  /** The business step again, for another business: loaded afresh, so with a new key. */
  againHref: string;
}

interface Attempt {
  state: ActionState<BusinessFormResult>;
  values: Record<string, string>;
  count: number;
}

/**
 * The business step's form: the GSTIN, the business name and an optional registration name.
 * Submitting creates the business; the answer replaces the form with what the GSTIN lookup
 * returned and the way on to the questions. A refused submit keeps what was typed (the fields
 * remount from the submitted values), shows the service's problem or the fields to fix, and moves
 * focus to the error summary; the submit button is disabled and busy while the action runs.
 */
export function BusinessForm({ action, idempotencyInput, fields, againHref }: BusinessFormProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: Object.fromEntries(
        Object.values(fields).map((name) => [name, String(formData.get(name) ?? "")]),
      ),
      count: previous.count + 1,
    }),
    { state: idleAction<BusinessFormResult>(), values: {}, count: 0 },
  );
  const { state } = attempt;
  const errorsRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (attempt.count === 0) return;
    if (attempt.state.status === "error") errorsRef.current?.focus();
    if (attempt.state.status === "ok") resultRef.current?.focus();
  }, [attempt]);

  if (state.status === "ok" && state.value !== undefined) {
    const result = state.value;
    return (
      <div data-slot="business-result" className="flex flex-col gap-6">
        <PrefillPanel result={result} headingRef={resultRef} />
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href={result.nextHref as Route}>
              {result.complete ? t("businessStep.toSummary") : t("businessStep.toQuestions")}
            </Link>
          </Button>
          <Button asChild variant="secondary">
            {/* A document load, not a client navigation: the step renders again with a new
                Idempotency-Key and an empty form. */}
            <a href={againHref}>{t("businessStep.another")}</a>
          </Button>
        </div>
      </div>
    );
  }

  const problem = state.status === "error" ? state.problem : undefined;
  return (
    <div data-slot="business-form" className="flex flex-col gap-6">
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="business-errors"
          className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
        >
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
            />
          ) : (
            <Banner tone="danger" title={t("businessStep.refused")}>
              {t("businessStep.checkFields")}
            </Banner>
          )}
        </div>
      ) : null}
      <form action={formAction} className="flex max-w-xl flex-col gap-4" key={attempt.count}>
        {idempotencyInput}
        <Field
          id="business-gstin"
          label={t("businessStep.gstin")}
          description={t("businessStep.gstinHelp")}
          error={fieldErrorOf(state, fields.gstin)}
          required
        >
          <Input
            name={fields.gstin}
            defaultValue={attempt.values[fields.gstin]}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={20}
          />
        </Field>
        <Field
          id="business-name"
          label={t("businessStep.name")}
          description={t("businessStep.nameHelp")}
          error={fieldErrorOf(state, fields.name)}
          required
        >
          <Input
            name={fields.name}
            defaultValue={attempt.values[fields.name]}
            autoComplete="organization"
            maxLength={200}
          />
        </Field>
        <Field
          id="business-registration-name"
          label={t("businessStep.registrationName")}
          description={t("businessStep.registrationNameHelp")}
          error={fieldErrorOf(state, fields.registrationName)}
        >
          <Input
            name={fields.registrationName}
            defaultValue={attempt.values[fields.registrationName]}
            autoComplete="off"
            maxLength={200}
          />
        </Field>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("businessStep.pending") : t("businessStep.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
