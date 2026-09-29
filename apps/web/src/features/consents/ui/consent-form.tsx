"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef, useState } from "react";
import { Banner, Button, Checkbox, ErrorState, Field, Input, Label } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type ConsentAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

/** One checkbox as the page builds it (the consent model's ConsentOption, structurally). */
export interface ConsentFormOption {
  purpose: string;
  label: string;
  required: boolean;
  document: { title: string; version: string };
  /** /legal/<document>. */
  documentHref: string;
  /** When the current grant was recorded (IST); null while the purpose is not granted. */
  grantedAt: string | null;
}

export interface ConsentFormProps {
  action: ConsentAction;
  options: readonly ConsentFormOption[];
  /** False for a CA firm: the WhatsApp box is not in `options` and a note says why. */
  offerWhatsapp: boolean;
  /** The form field of the WhatsApp number. */
  whatsappField: string;
  /** The consents settings page, where an optional purpose is withdrawn; null without access. */
  settingsHref: string | null;
}

interface Values {
  purposes: readonly string[];
  whatsappNumber: string;
}

interface Attempt {
  state: ActionState;
  values: Values;
  count: number;
}

const WHATSAPP = "whatsapp_reminders";

function valuesOf(
  formData: FormData,
  options: readonly ConsentFormOption[],
  field: string,
): Values {
  const number = formData.get(field);
  return {
    purposes: options.map((o) => o.purpose).filter((purpose) => formData.get(purpose) !== null),
    whatsappNumber: typeof number === "string" ? number : "",
  };
}

/**
 * The consent checkboxes: the required ones (terms, privacy notice, profile processing), then
 * the optional ones (WhatsApp reminders with the number they go to, email reminders, product
 * analytics), each unticked, each with the document it refers to and its version. A purpose
 * already granted at the current version is not a box but a line saying when it was agreed:
 * submitting records only boxes that are ticked, so a pre-ticked box that was unticked would
 * look like a withdrawal and record nothing. An optional one links to the settings page, where
 * it is withdrawn. The number field appears only while the WhatsApp box is ticked. A refused submit shows the service's problem or the fields to fix, keeps what was
 * ticked and typed (the fields remount from the submitted values), and moves focus to the
 * error summary; the submit button is disabled and busy while the action runs.
 */
export function ConsentForm({
  action,
  options,
  offerWhatsapp,
  whatsappField,
  settingsHref,
}: ConsentFormProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: valuesOf(formData, options, whatsappField),
      count: previous.count + 1,
    }),
    { state: idleAction(), values: { purposes: [], whatsappNumber: "" }, count: 0 },
  );
  const { state } = attempt;
  const errorsRef = useRef<HTMLDivElement>(null);
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") errorsRef.current?.focus();
  }, [attempt]);

  return (
    <div data-slot="consent-form" className="flex flex-col gap-6">
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="consent-errors"
          className="flex flex-col gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
        >
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
            />
          ) : null}
          {formErrors.length > 0 ? (
            <Banner tone="danger" title={t("consent.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!problem && formErrors.length === 0 ? (
            <Banner tone="danger" title={t("consent.refused")}>
              {t("consent.checkFields")}
            </Banner>
          ) : null}
        </div>
      ) : null}
      <form action={formAction} className="flex flex-col gap-6" data-slot="consent-fields">
        <ConsentFields
          key={attempt.count}
          options={options}
          initial={attempt.values}
          state={state}
          offerWhatsapp={offerWhatsapp}
          whatsappField={whatsappField}
          settingsHref={settingsHref}
        />
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("consent.pending") : t("consent.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}

interface ConsentFieldsProps {
  options: readonly ConsentFormOption[];
  initial: Values;
  state: ActionState;
  offerWhatsapp: boolean;
  whatsappField: string;
  settingsHref: string | null;
}

function DocumentLink({ option }: { option: ConsentFormOption }) {
  return (
    <Link href={option.documentHref as Route} className="text-primary underline">
      {t("consent.document", {
        title: option.document.title,
        version: option.document.version,
      })}
    </Link>
  );
}

/** A purpose granted at the current version: what was agreed, when, and where to withdraw it. */
function Agreed({
  option,
  date,
  settingsHref,
}: {
  option: ConsentFormOption;
  date: string;
  settingsHref: string | null;
}) {
  return (
    <div className="grid gap-0.5" data-purpose={option.purpose} data-slot="consent-agreed">
      <p className="text-sm leading-snug text-fg">{option.label}</p>
      <p className="text-xs text-fg-muted">
        {t("consent.agreedOn", { date })} <DocumentLink option={option} />
      </p>
      {option.required || settingsHref === null ? null : (
        <p className="text-xs">
          <Link href={settingsHref as Route} className="text-primary underline">
            {t("consent.withdrawInSettings")}
          </Link>
        </p>
      )}
    </div>
  );
}

function ConsentFields({
  options,
  initial,
  state,
  offerWhatsapp,
  whatsappField,
  settingsHref,
}: ConsentFieldsProps) {
  const id = useId();
  const [whatsapp, setWhatsapp] = useState(initial.purposes.includes(WHATSAPP));
  const required = options.filter((option) => option.required);
  const optional = options.filter((option) => !option.required);

  const box = (option: ConsentFormOption) => {
    if (option.grantedAt !== null) {
      return (
        <Agreed
          key={option.purpose}
          option={option}
          date={option.grantedAt}
          settingsHref={settingsHref}
        />
      );
    }
    const boxId = `${id}-${option.purpose}`;
    const documentId = `${boxId}-document`;
    const errorId = `${boxId}-error`;
    const error = fieldErrorOf(state, option.purpose);
    return (
      <div key={option.purpose} className="grid gap-1" data-purpose={option.purpose}>
        <div className="flex items-start gap-2">
          <Checkbox
            id={boxId}
            name={option.purpose}
            defaultChecked={initial.purposes.includes(option.purpose)}
            onCheckedChange={
              option.purpose === WHATSAPP ? (checked) => setWhatsapp(checked === true) : undefined
            }
            aria-describedby={error ? `${documentId} ${errorId}` : documentId}
            aria-invalid={error ? true : undefined}
            className="mt-0.5"
          />
          <div className="grid gap-0.5">
            <Label htmlFor={boxId} className="leading-snug">
              {option.label}
            </Label>
            <p id={documentId} className="text-xs text-fg-muted">
              <DocumentLink option={option} />
            </p>
          </div>
        </div>
        {error ? (
          <p id={errorId} data-slot="field-error" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
    );
  };

  return (
    <>
      <fieldset className="grid gap-3">
        <legend className="mb-1 text-sm font-semibold text-fg">
          {t("consent.requiredLegend")}
        </legend>
        {required.map(box)}
      </fieldset>
      <fieldset className="grid gap-3">
        <legend className="mb-1 text-sm font-semibold text-fg">
          {t("consent.optionalLegend")}
        </legend>
        {optional.map((option) => (
          <div key={option.purpose} className="grid gap-3">
            {box(option)}
            {option.purpose === WHATSAPP && whatsapp ? (
              <Field
                id={`${id}-whatsapp-number`}
                label={t("consent.whatsappNumber")}
                description={t("consent.whatsappNumberHelp")}
                error={fieldErrorOf(state, whatsappField)}
                required
                className="ml-6 max-w-sm"
              >
                <Input
                  name={whatsappField}
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  defaultValue={initial.whatsappNumber}
                />
              </Field>
            ) : null}
          </div>
        ))}
        {offerWhatsapp ? null : <p className="text-sm text-fg-muted">{t("consent.caFirmNote")}</p>}
      </fieldset>
    </>
  );
}
