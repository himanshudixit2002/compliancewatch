"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useId } from "react";
import {
  Banner,
  Button,
  ErrorState,
  Field,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  Select,
  describedBy,
  fieldIds,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type PreferenceAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface PreferenceFormProps {
  action: PreferenceAction;
  channel: string;
  /** The recipient as a person reads it, to name the form. */
  recipient: string;
  fields: {
    channel: string;
    optedIn: string;
    language: string;
    quietStart: string;
    quietEnd: string;
  };
  values: { optedIn: boolean; language: string; quietHoursStart: string; quietHoursEnd: string };
  languages: readonly { value: string; label: string }[];
  /** False while the user's consent to the channel's reminders is not on file. */
  consentGiven: boolean;
  purposeLabel: string;
  consentsHref: string;
}

/**
 * One recipient's preference: send reminders or not, the language, and the quiet hours in IST
 * (both ends, on the 24-hour clock). Saving replaces the preference on the notification
 * service; the answer says what is now recorded, in a status line. While the user's consent to
 * the channel's reminders is not on file, the form says so and the action refuses an opt-in.
 */
export function PreferenceForm({
  action,
  channel,
  recipient,
  fields,
  values,
  languages,
  consentGiven,
  purposeLabel,
  consentsHref,
}: PreferenceFormProps) {
  const id = useId();
  const [state, formAction, pending] = useActionState(action, idleAction());
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const optedError = fieldErrorOf(state, fields.optedIn);
  const opted = fieldIds(`${id}-opted`);
  const optedLabel = `${id}-opted-label`;
  return (
    <form
      action={formAction}
      aria-label={t("notifications.formLabel", { recipient })}
      data-slot="preference-form"
      data-channel={channel}
      className="flex max-w-xl flex-col gap-5"
    >
      <input type="hidden" name={fields.channel} value={channel} />
      <h3 className="text-base font-semibold text-fg">{t("notifications.formTitle")}</h3>
      {consentGiven ? null : (
        <Banner
          tone="info"
          title={t("notifications.consentMissingTitle", { purpose: purposeLabel })}
        >
          {t("notifications.consentMissing")}{" "}
          <Link href={consentsHref as Route} className="underline">
            {t("notifications.toConsents")}
          </Link>
        </Banner>
      )}
      <div className="grid gap-2">
        <span id={optedLabel} className="text-sm font-medium text-fg">
          {t("notifications.optedInLegend")}
        </span>
        <RadioGroup
          id={opted.control}
          name={fields.optedIn}
          defaultValue={values.optedIn ? "in" : "out"}
          aria-labelledby={optedLabel}
          aria-describedby={describedBy(optedError ? opted.error : undefined)}
          aria-invalid={optedError ? true : undefined}
          className="gap-2"
        >
          {(["in", "out"] as const).map((value) => (
            <div key={value} className="flex items-center gap-2">
              <RadioGroupItem id={`${opted.control}-${value}`} value={value} />
              <Label htmlFor={`${opted.control}-${value}`}>
                {value === "in" ? t("notifications.choice.in") : t("notifications.choice.out")}
              </Label>
            </div>
          ))}
        </RadioGroup>
        {optedError ? (
          <p id={opted.error} data-slot="field-error" className="text-sm text-danger">
            {optedError}
          </p>
        ) : null}
      </div>
      <Field
        id={`${id}-language`}
        label={t("notifications.language")}
        description={t("notifications.languageHelp")}
        error={fieldErrorOf(state, fields.language)}
        className="max-w-xs"
      >
        <Select name={fields.language} defaultValue={values.language} options={languages} />
      </Field>
      <fieldset className="grid gap-2" aria-describedby={`${id}-quiet-help`}>
        <legend className="mb-1 text-sm font-medium text-fg">
          {t("notifications.quietLegend")}
        </legend>
        <p id={`${id}-quiet-help`} className="text-sm text-fg-muted">
          {t("notifications.quietHelp")}
        </p>
        <div className="grid max-w-md gap-3 sm:grid-cols-2">
          <Field
            id={`${id}-quiet-start`}
            label={t("notifications.quietStart")}
            error={fieldErrorOf(state, fields.quietStart)}
            required
          >
            <Input name={fields.quietStart} type="time" defaultValue={values.quietHoursStart} />
          </Field>
          <Field
            id={`${id}-quiet-end`}
            label={t("notifications.quietEnd")}
            error={fieldErrorOf(state, fields.quietEnd)}
            required
          >
            <Input name={fields.quietEnd} type="time" defaultValue={values.quietHoursEnd} />
          </Field>
        </div>
      </fieldset>
      {problem ? (
        <ErrorState
          title={problem.title}
          detail={problem.detail}
          correlationId={problem.correlationId || undefined}
        />
      ) : null}
      {formErrors.length > 0 ? (
        <Banner tone="danger" title={t("notifications.refused")}>
          <ul>
            {formErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
          {pending ? t("notifications.saving") : t("notifications.save")}
        </Button>
        <p role="status" data-slot="preference-status" className="text-sm text-fg-muted">
          {state.status === "ok" ? state.message : ""}
        </p>
      </div>
    </form>
  );
}
