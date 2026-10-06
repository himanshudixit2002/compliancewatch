"use client";

import { startTransition, useActionState, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Button, ErrorState, Field, Input, Select, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import { levelLabel } from "@/shared/ui/applicability";
import { DryRunReport } from "./dry-run-report";
import {
  DRY_RUN_FIELDS,
  MAX_SAMPLES,
  type DryRunAnswer,
  type DryRunFormValues,
  type DryRunSubject,
  type LevelChoice,
} from "./dry-run-shared";

export type DryRunAction = (
  state: ActionState<DryRunAnswer>,
  formData: FormData,
) => Promise<ActionState<DryRunAnswer>>;

export interface DryRunFormProps {
  action: DryRunAction;
  initial: DryRunFormValues;
}

const LEVELS: readonly Exclude<LevelChoice, "">[] = ["entity", "registration", "location"];

/**
 * The dry run: what to run (a rule version by its id, or a specification as the kernel's
 * predicate tree in JSON with the level it is decided at) and over which businesses (one tenant
 * or every tenant, and how many decisions to keep as samples). The form keeps what was sent
 * whatever came of it, says each field's refusal under the field, and shows the report below.
 */
export function DryRunForm({ action, initial }: DryRunFormProps) {
  const [values, setValues] = useState<DryRunFormValues>(initial);
  const [state, dispatch, pending] = useActionState(
    async (_previous: ActionState<DryRunAnswer>, formData: FormData) =>
      action(idleAction(), formData),
    idleAction<DryRunAnswer>(),
  );
  const [sent, setSent] = useState(0);
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sent > 0 && !pending) outcomeRef.current?.focus();
  }, [sent, pending]);
  const set = (field: keyof DryRunFormValues) => (value: string) =>
    setValues((current) => ({ ...current, [field]: value }));
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData();
    formData.set(DRY_RUN_FIELDS.subject, values.subject);
    formData.set(DRY_RUN_FIELDS.ruleVersionId, values.ruleVersionId);
    formData.set(DRY_RUN_FIELDS.specification, values.specification);
    formData.set(DRY_RUN_FIELDS.level, values.level);
    formData.set(DRY_RUN_FIELDS.tenantId, values.tenantId);
    formData.set(DRY_RUN_FIELDS.sampleSize, values.sampleSize);
    setSent((count) => count + 1);
    startTransition(() => dispatch(formData));
  };
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  return (
    <div className="flex flex-col gap-6">
      <form
        aria-label={t("impact.form.label")}
        data-slot="dry-run-form"
        noValidate
        onSubmit={submit}
        className="flex max-w-3xl flex-col gap-4"
      >
        <Field id="dry-run-subject" label={t("impact.form.subject")}>
          <Select
            name={DRY_RUN_FIELDS.subject}
            value={values.subject}
            onChange={(event) => set("subject")(event.target.value as DryRunSubject)}
            options={[
              { value: "version", label: t("impact.form.subjectVersion") },
              { value: "specification", label: t("impact.form.subjectSpecification") },
            ]}
          />
        </Field>
        {values.subject === "version" ? (
          <Field
            id="dry-run-version"
            label={t("impact.form.version")}
            description={t("impact.form.versionHelp")}
            error={fieldErrorOf(state, DRY_RUN_FIELDS.ruleVersionId)}
            required
          >
            <Input
              name={DRY_RUN_FIELDS.ruleVersionId}
              value={values.ruleVersionId}
              onChange={(event) => set("ruleVersionId")(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        ) : (
          <Field
            id="dry-run-specification"
            label={t("impact.form.specification")}
            description={t("impact.form.specificationHelp")}
            error={fieldErrorOf(state, DRY_RUN_FIELDS.specification)}
            required
          >
            <Textarea
              name={DRY_RUN_FIELDS.specification}
              value={values.specification}
              onChange={(event) => set("specification")(event.target.value)}
              rows={8}
              spellCheck={false}
              className="font-mono text-xs"
            />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            id="dry-run-level"
            label={t("impact.form.level")}
            description={
              values.subject === "version"
                ? t("impact.form.levelVersionHelp")
                : t("impact.form.levelSpecificationHelp")
            }
            error={fieldErrorOf(state, DRY_RUN_FIELDS.level)}
            required={values.subject === "specification"}
          >
            <Select
              name={DRY_RUN_FIELDS.level}
              value={values.level}
              onChange={(event) => set("level")(event.target.value)}
              options={[
                { value: "", label: t("impact.form.levelDefault") },
                ...LEVELS.map((level) => ({ value: level, label: levelLabel(level) })),
              ]}
            />
          </Field>
          <Field
            id="dry-run-tenant"
            label={t("impact.form.tenant")}
            description={t("impact.form.tenantHelp")}
            error={fieldErrorOf(state, DRY_RUN_FIELDS.tenantId)}
          >
            <Input
              name={DRY_RUN_FIELDS.tenantId}
              value={values.tenantId}
              onChange={(event) => set("tenantId")(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Field
            id="dry-run-samples"
            label={t("impact.form.samples")}
            description={t("impact.form.samplesHelp", { max: MAX_SAMPLES })}
            error={fieldErrorOf(state, DRY_RUN_FIELDS.sampleSize)}
          >
            <Input
              name={DRY_RUN_FIELDS.sampleSize}
              value={values.sampleSize}
              onChange={(event) => set("sampleSize")(event.target.value)}
              inputMode="numeric"
              autoComplete="off"
            />
          </Field>
        </div>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {t("impact.form.submit")}
          </Button>
        </div>
      </form>
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="dry-run-outcome"
        className="flex flex-col gap-4 outline-none"
      >
        <p role="status" className="text-sm text-fg-muted">
          {pending ? t("impact.form.running") : state.status === "ok" ? (state.message ?? "") : ""}
        </p>
        {state.status === "error" ? (
          <>
            {state.problem === undefined ? null : (
              <ErrorState
                title={state.problem.title}
                detail={state.problem.detail}
                correlationId={state.problem.correlationId || undefined}
              />
            )}
            {formErrors.map((message, index) => (
              <p key={index} role="alert" className="text-sm text-danger">
                {message}
              </p>
            ))}
          </>
        ) : null}
      </div>
      {state.status === "ok" && state.value !== undefined ? (
        <DryRunReport report={state.value.report} />
      ) : null}
    </div>
  );
}
