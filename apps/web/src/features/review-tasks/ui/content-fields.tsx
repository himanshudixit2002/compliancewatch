"use client";

import { useState } from "react";
import { Field, Input, Select, Textarea } from "@compliancewatch/ui";
import { FREQUENCIES } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import {
  BASE_PREFIX,
  CONTENT_FIELDS,
  LIMITS,
  type ContentValues,
  type EditorOntology,
  type Frequency,
} from "./form-shared";
import { PredicateEditor } from "./predicate-editor";

export interface ContentFieldsProps {
  /** Unique within the page, for the controls' ids. */
  idPrefix: string;
  /** The form names' prefix: "" for an edit, "edits." for a draft from a candidate. */
  prefix: string;
  initial: ContentValues;
  ontology: EditorOntology | null;
  disabled: boolean;
  /** The action's field errors, by the names the form posts. */
  errors: Readonly<Record<string, readonly string[]>>;
  /** Show the condition's shape problems: the form was submitted with some. */
  showErrors: boolean;
  /** How many shape problems the condition has now. */
  onProblems: (count: number) => void;
}

const FREQUENCY_KEYS: Readonly<Record<Frequency, MessageKey>> = {
  monthly: "workbench.frequency.monthly",
  quarterly: "workbench.frequency.quarterly",
  half_yearly: "workbench.frequency.half_yearly",
  annual: "workbench.frequency.annual",
};

/** The base value of a field: what it was rendered with, posted beside it. */
function Base({ name, value }: { name: string; value: string }) {
  return <input type="hidden" name={`${BASE_PREFIX}${name}`} value={value} />;
}

/**
 * A draft's content as form fields, each posted with the value it was rendered with so only the
 * fields an analyst changed are sent: the title and summary, the effective period, how the duty
 * recurs, the obligation it creates, the open questions, and the condition in the predicate
 * editor. Every control has a label, and an error from the action sits under its field.
 */
export function ContentFields({
  idPrefix,
  prefix,
  initial,
  ontology,
  disabled,
  errors,
  showErrors,
  onProblems,
}: ContentFieldsProps) {
  const [values, setValues] = useState<ContentValues>(initial);
  const name = (field: string) => `${prefix}${field}`;
  const error = (field: string) => errors[name(field)];
  const id = (field: string) => `${idPrefix}-${field.replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const set = (field: keyof ContentValues) => (value: string) =>
    setValues((current) => ({ ...current, [field]: value }));
  const specificationError = error(CONTENT_FIELDS.specification)?.join(" ");

  return (
    <div className="flex flex-col gap-5" data-slot="content-fields">
      <Field
        id={id(CONTENT_FIELDS.title)}
        label={t("workbench.field.title")}
        error={error(CONTENT_FIELDS.title)}
        required
      >
        <Input
          name={name(CONTENT_FIELDS.title)}
          value={values.title}
          maxLength={LIMITS.title}
          disabled={disabled}
          onChange={(event) => set("title")(event.target.value)}
        />
      </Field>
      <Base name={name(CONTENT_FIELDS.title)} value={initial.title} />
      <Field
        id={id(CONTENT_FIELDS.summary)}
        label={t("workbench.field.summary")}
        error={error(CONTENT_FIELDS.summary)}
      >
        <Textarea
          name={name(CONTENT_FIELDS.summary)}
          value={values.summary}
          rows={4}
          maxLength={LIMITS.summary}
          disabled={disabled}
          onChange={(event) => set("summary")(event.target.value)}
        />
      </Field>
      <Base name={name(CONTENT_FIELDS.summary)} value={initial.summary} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={id(CONTENT_FIELDS.effectiveFrom)}
          label={t("workbench.field.effectiveFrom")}
          error={error(CONTENT_FIELDS.effectiveFrom)}
          required
        >
          <Input
            type="date"
            name={name(CONTENT_FIELDS.effectiveFrom)}
            value={values.effectiveFrom}
            disabled={disabled}
            onChange={(event) => set("effectiveFrom")(event.target.value)}
          />
        </Field>
        <Field
          id={id(CONTENT_FIELDS.effectiveTo)}
          label={t("workbench.field.effectiveTo")}
          description={t("workbench.field.effectiveToHelp")}
          error={error(CONTENT_FIELDS.effectiveTo)}
        >
          <Input
            type="date"
            name={name(CONTENT_FIELDS.effectiveTo)}
            value={values.effectiveTo}
            disabled={disabled}
            onChange={(event) => set("effectiveTo")(event.target.value)}
          />
        </Field>
      </div>
      <Base name={name(CONTENT_FIELDS.effectiveFrom)} value={initial.effectiveFrom} />
      <Base name={name(CONTENT_FIELDS.effectiveTo)} value={initial.effectiveTo} />
      <fieldset className="flex flex-col gap-3" data-slot="recurrence-fields">
        <legend className="text-sm font-semibold text-fg">{t("workbench.field.recurrence")}</legend>
        <Field
          id={id(CONTENT_FIELDS.frequency)}
          label={t("workbench.field.frequency")}
          error={error(CONTENT_FIELDS.frequency)}
          className="max-w-sm"
        >
          <Select
            name={name(CONTENT_FIELDS.frequency)}
            value={values.frequency}
            disabled={disabled}
            onChange={(event) => set("frequency")(event.target.value)}
            options={[
              { value: "", label: t("workbench.recurrence.none") },
              ...FREQUENCIES.map((frequency) => ({
                value: frequency,
                label: t(FREQUENCY_KEYS[frequency]),
              })),
            ]}
          />
        </Field>
        {values.frequency === "" ? (
          <p className="text-sm text-fg-muted">{t("workbench.field.oneOff")}</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id={id(CONTENT_FIELDS.dueDay)}
              label={t("workbench.field.dueDay")}
              description={t("workbench.field.dueDayHelp", { max: LIMITS.dueDay })}
              error={error(CONTENT_FIELDS.dueDay)}
              required
            >
              <Input
                inputMode="numeric"
                name={name(CONTENT_FIELDS.dueDay)}
                value={values.dueDay}
                disabled={disabled}
                onChange={(event) => set("dueDay")(event.target.value)}
              />
            </Field>
            <Field
              id={id(CONTENT_FIELDS.dueMonthOffset)}
              label={t("workbench.field.dueMonthOffset")}
              description={t("workbench.field.dueMonthOffsetHelp", { max: LIMITS.dueMonthOffset })}
              error={error(CONTENT_FIELDS.dueMonthOffset)}
            >
              <Input
                inputMode="numeric"
                name={name(CONTENT_FIELDS.dueMonthOffset)}
                value={values.dueMonthOffset}
                disabled={disabled}
                onChange={(event) => set("dueMonthOffset")(event.target.value)}
              />
            </Field>
          </div>
        )}
      </fieldset>
      <Base name={name(CONTENT_FIELDS.frequency)} value={initial.frequency} />
      <Base name={name(CONTENT_FIELDS.dueDay)} value={initial.dueDay} />
      <Base name={name(CONTENT_FIELDS.dueMonthOffset)} value={initial.dueMonthOffset} />
      <fieldset className="flex flex-col gap-3" data-slot="template-fields">
        <legend className="text-sm font-semibold text-fg">{t("workbench.field.template")}</legend>
        <Field
          id={id(CONTENT_FIELDS.templateTitle)}
          label={t("workbench.field.templateTitle")}
          error={error(CONTENT_FIELDS.templateTitle)}
          required
        >
          <Input
            name={name(CONTENT_FIELDS.templateTitle)}
            value={values.templateTitle}
            disabled={disabled}
            onChange={(event) => set("templateTitle")(event.target.value)}
          />
        </Field>
        <Field
          id={id(CONTENT_FIELDS.templateSteps)}
          label={t("workbench.field.templateSteps")}
          description={t("workbench.field.linesHelp")}
          error={error(CONTENT_FIELDS.templateSteps)}
        >
          <Textarea
            name={name(CONTENT_FIELDS.templateSteps)}
            value={values.templateSteps}
            rows={3}
            disabled={disabled}
            onChange={(event) => set("templateSteps")(event.target.value)}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={id(CONTENT_FIELDS.templateDueInDays)}
            label={t("workbench.field.dueInDays")}
            description={t("workbench.field.dueInDaysHelp")}
            error={error(CONTENT_FIELDS.templateDueInDays)}
          >
            <Input
              inputMode="numeric"
              name={name(CONTENT_FIELDS.templateDueInDays)}
              value={values.templateDueInDays}
              disabled={disabled}
              onChange={(event) => set("templateDueInDays")(event.target.value)}
            />
          </Field>
          <Field
            id={id(CONTENT_FIELDS.templateEvidence)}
            label={t("workbench.field.evidence")}
            error={error(CONTENT_FIELDS.templateEvidence)}
          >
            <Input
              name={name(CONTENT_FIELDS.templateEvidence)}
              value={values.templateEvidence}
              disabled={disabled}
              onChange={(event) => set("templateEvidence")(event.target.value)}
            />
          </Field>
        </div>
      </fieldset>
      <Base name={name(CONTENT_FIELDS.templateTitle)} value={initial.templateTitle} />
      <Base name={name(CONTENT_FIELDS.templateSteps)} value={initial.templateSteps} />
      <Base name={name(CONTENT_FIELDS.templateDueInDays)} value={initial.templateDueInDays} />
      <Base name={name(CONTENT_FIELDS.templateEvidence)} value={initial.templateEvidence} />
      <Field
        id={id(CONTENT_FIELDS.todo)}
        label={t("workbench.field.todo")}
        description={t("workbench.field.todoHelp", { max: LIMITS.todo })}
        error={error(CONTENT_FIELDS.todo)}
      >
        <Textarea
          name={name(CONTENT_FIELDS.todo)}
          value={values.todo}
          rows={3}
          disabled={disabled}
          onChange={(event) => set("todo")(event.target.value)}
        />
      </Field>
      <Base name={name(CONTENT_FIELDS.todo)} value={initial.todo} />
      <PredicateEditor
        idPrefix={`${idPrefix}-spec`}
        name={name(CONTENT_FIELDS.specification)}
        baseName={`${BASE_PREFIX}${name(CONTENT_FIELDS.specification)}`}
        initial={initial.specification}
        ontology={ontology}
        disabled={disabled}
        showErrors={showErrors}
        {...(specificationError === undefined ? {} : { error: specificationError })}
        onProblems={onProblems}
      />
    </div>
  );
}
