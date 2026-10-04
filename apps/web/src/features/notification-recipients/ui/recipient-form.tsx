"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef } from "react";
import {
  Banner,
  Button,
  CheckboxGroup,
  ErrorState,
  Field,
  Input,
  Select,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type RecipientFormAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface FormOption {
  value: string;
  label: string;
}

/** The form as the page renders it (the recipients model's RecipientFormView, structurally). */
export interface RecipientFormData {
  mode: "add" | "change";
  recipientId: string;
  name: string;
  values: {
    role: string;
    language: string;
    digestMode: string;
    orgLabel: string;
    addresses: readonly { channel: string; address: string }[];
    businessIds: readonly string[];
  };
  roles: readonly FormOption[];
  languages: readonly FormOption[];
  businesses: readonly FormOption[];
  addressRows: number;
}

export interface RecipientFormFields {
  recipientId: string;
  returnBusiness: string;
  role: string;
  language: string;
  digestMode: string;
  orgLabel: string;
  businesses: string;
  /** One name per address row, in order: `addresses.0.address` ... */
  addresses: readonly string[];
  /** The channel field of each address row. */
  channels: readonly string[];
}

export interface RecipientFormProps {
  action: RecipientFormAction;
  form: RecipientFormData;
  /** The business the page shows, to come back to. */
  returnBusiness: string;
  fields: RecipientFormFields;
  channels: readonly FormOption[];
  digestModes: readonly FormOption[];
  /** The page without the recipient being changed; null for the add form. */
  cancelHref: string | null;
}

interface Submitted {
  role: string;
  language: string;
  digestMode: string;
  orgLabel: string;
  rows: { channel: string; address: string }[];
  businessIds: string[];
}

interface Attempt {
  state: ActionState;
  submitted: Submitted | null;
  count: number;
}

function read(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

/**
 * Adds a recipient for the business, or changes one: the role, the organisation it speaks for,
 * its addresses in the order they are tried, the language, the delivery, and the businesses it
 * hears about. The values go to the server in the POST body; a refused form comes back with what
 * was submitted and moves focus to the summary of what to fix. A saved one returns to the page,
 * which says what was saved.
 */
export function RecipientForm({
  action,
  form,
  returnBusiness,
  fields,
  channels,
  digestModes,
  cancelHref,
}: RecipientFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      submitted: {
        role: read(formData, fields.role),
        language: read(formData, fields.language),
        digestMode: read(formData, fields.digestMode),
        orgLabel: read(formData, fields.orgLabel),
        rows: fields.addresses.map((name, index) => ({
          channel: read(formData, fields.channels[index] ?? ""),
          address: read(formData, name),
        })),
        businessIds: formData.getAll(fields.businesses).map(String),
      },
      count: previous.count + 1,
    }),
    { state: idleAction(), submitted: null, count: 0 },
  );
  const { state } = attempt;
  const summaryRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") summaryRef.current?.focus();
  }, [attempt]);

  const refused = state.status === "error" && attempt.submitted !== null;
  const shown: Submitted =
    refused && attempt.submitted !== null
      ? attempt.submitted
      : {
          ...form.values,
          rows: Array.from({ length: form.addressRows }, (_, index) => ({
            channel:
              form.values.addresses[index]?.channel ?? (index % 2 === 0 ? "whatsapp" : "email"),
            address: form.values.addresses[index]?.address ?? "",
          })),
          businessIds: [...form.values.businessIds],
        };
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const title =
    form.mode === "add" ? t("recipients.formAdd") : t("recipients.formChange", { name: form.name });
  return (
    <form
      action={formAction}
      aria-label={title}
      noValidate
      data-slot="recipient-form"
      data-mode={form.mode}
      className="flex max-w-2xl flex-col gap-5"
    >
      <input type="hidden" name={fields.recipientId} value={form.recipientId} />
      <input type="hidden" name={fields.returnBusiness} value={returnBusiness} />
      <div
        ref={summaryRef}
        tabIndex={-1}
        data-slot="recipient-form-summary"
        className="flex flex-col gap-2 outline-none"
      >
        {problem ? (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        ) : null}
        {formErrors.length > 0 || (state.status === "error" && state.fieldErrors) ? (
          <Banner tone="danger" title={t("recipients.refused")}>
            {formErrors.length > 0 ? (
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            ) : (
              t("recipients.fixFields")
            )}
          </Banner>
        ) : null}
      </div>
      <div key={attempt.count} className="contents">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={`${id}-role`}
            label={t("recipients.field.role")}
            error={fieldErrorOf(state, fields.role)}
            required
          >
            <Select name={fields.role} defaultValue={shown.role} options={form.roles} />
          </Field>
          <Field
            id={`${id}-org`}
            label={t("recipients.field.orgLabel")}
            description={t("recipients.field.orgLabelHelp")}
            error={fieldErrorOf(state, fields.orgLabel)}
          >
            <Input
              name={fields.orgLabel}
              defaultValue={shown.orgLabel}
              maxLength={200}
              autoComplete="organization"
            />
          </Field>
        </div>
        <fieldset className="grid gap-3" aria-describedby={`${id}-addresses-help`}>
          <legend className="mb-1 text-sm font-medium text-fg">
            {t("recipients.field.addresses")}
          </legend>
          <p id={`${id}-addresses-help`} className="text-sm text-fg-muted">
            {t("recipients.field.addressesHelp")}
          </p>
          {shown.rows.map((row, index) => {
            const channelName = fields.channels[index] ?? "";
            const addressName = fields.addresses[index] ?? "";
            return (
              <div
                key={addressName}
                data-slot="address-row"
                className="grid gap-3 sm:grid-cols-[10rem_1fr]"
              >
                <Field
                  id={`${id}-channel-${index}`}
                  label={t("recipients.field.channel", { n: index + 1 })}
                  error={fieldErrorOf(state, channelName)}
                >
                  <Select name={channelName} defaultValue={row.channel} options={channels} />
                </Field>
                <Field
                  id={`${id}-address-${index}`}
                  label={t("recipients.field.address", { n: index + 1 })}
                  error={fieldErrorOf(state, addressName)}
                >
                  <Input name={addressName} defaultValue={row.address} autoComplete="off" />
                </Field>
              </div>
            );
          })}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={`${id}-language`}
            label={t("recipients.field.language")}
            description={t("recipients.field.languageHelp")}
            error={fieldErrorOf(state, fields.language)}
            required
          >
            <Select name={fields.language} defaultValue={shown.language} options={form.languages} />
          </Field>
          <Field
            id={`${id}-delivery`}
            label={t("recipients.field.delivery")}
            description={t("recipients.field.deliveryHelp")}
            error={fieldErrorOf(state, fields.digestMode)}
            required
          >
            <Select
              name={fields.digestMode}
              defaultValue={shown.digestMode}
              options={digestModes}
            />
          </Field>
        </div>
        <CheckboxGroup
          id={`${id}-businesses`}
          legend={t("recipients.field.businesses")}
          name={fields.businesses}
          options={form.businesses}
          defaultValue={shown.businessIds}
          error={fieldErrorOf(state, fields.businesses)}
          required
          columns={2}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
          {pending
            ? t("recipients.saving")
            : form.mode === "add"
              ? t("recipients.submitAdd")
              : t("recipients.submitChange")}
        </Button>
        {cancelHref === null ? null : (
          <Link
            href={cancelHref as Route}
            className="text-sm text-fg-muted underline hover:text-fg"
          >
            {t("common.cancel")}
          </Link>
        )}
      </div>
    </form>
  );
}
