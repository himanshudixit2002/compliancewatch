"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  Banner,
  Button,
  ErrorState,
  Field,
  Input,
  Label,
  PageHeader,
  RadioGroup,
  RadioGroupItem,
  describedBy,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type SignUpAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface SignUpFormFields {
  kind: string;
  name: string;
  displayName: string;
}

export interface SignUpKindOption {
  value: string;
  label: string;
  description: string;
  /** The kind's first role needs a second factor before the account exists. */
  needsMfa: boolean;
}

export interface SignUpFormProps {
  action: SignUpAction;
  fields: SignUpFormFields;
  kinds: readonly SignUpKindOption[];
  /** The verified contact the account is made for, to say so. */
  contact: string;
}

interface Attempt {
  state: ActionState;
  values: { kind: string; name: string; displayName: string };
  count: number;
}

function textOf(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value : "";
}

/**
 * The sign-up form for a person identity does not know yet: the kind of account (a business
 * or a CA firm), its name, and the person's own name. The fields remount from what was sent
 * after a refused submit, and focus moves to the errors.
 */
export function SignUpForm({ action, fields, kinds, contact }: SignUpFormProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: {
        kind: textOf(formData.get(fields.kind)),
        name: textOf(formData.get(fields.name)),
        displayName: textOf(formData.get(fields.displayName)),
      },
      count: previous.count + 1,
    }),
    {
      state: idleAction(),
      values: { kind: kinds[0]?.value ?? "", name: "", displayName: "" },
      count: 0,
    },
  );
  const { state, values } = attempt;
  const errorsRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const kindError = fieldErrorOf(state, fields.kind);
  const kindErrorId = `${id}-kind-error`;
  const kindLabelId = `${id}-kind-label`;

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") errorsRef.current?.focus();
  }, [attempt]);

  return (
    <div data-slot="sign-up" className="flex max-w-xl flex-col gap-6">
      <PageHeader title={t("signUp.title")} description={t("signUp.intro", { contact })} />
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="sign-up-errors"
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
            <Banner tone="danger" title={t("signUp.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!problem && formErrors.length === 0 ? (
            <Banner tone="danger" title={t("signUp.refused")}>
              {t("signIn.checkFields")}
            </Banner>
          ) : null}
        </div>
      ) : null}
      <form
        key={attempt.count}
        action={formAction}
        className="flex flex-col gap-5"
        data-slot="sign-up-form"
      >
        <div className="grid gap-2">
          <span id={kindLabelId} className="text-sm font-medium text-fg">
            {t("signUp.kind")}
          </span>
          <RadioGroup
            name={fields.kind}
            defaultValue={values.kind}
            aria-labelledby={kindLabelId}
            aria-describedby={describedBy(kindError ? kindErrorId : undefined)}
            aria-invalid={kindError ? true : undefined}
            className="gap-3"
          >
            {kinds.map((kind) => (
              <div key={kind.value} className="flex items-start gap-2">
                <RadioGroupItem
                  id={`${id}-kind-${kind.value}`}
                  value={kind.value}
                  className="mt-1"
                />
                <Label htmlFor={`${id}-kind-${kind.value}`} className="flex flex-col gap-0.5">
                  <span>{kind.label}</span>
                  <span className="text-sm font-normal text-fg-muted">
                    {kind.description}
                    {kind.needsMfa ? ` ${t("signUp.kindNeedsMfa")}` : ""}
                  </span>
                </Label>
              </div>
            ))}
          </RadioGroup>
          {kindError ? (
            <p id={kindErrorId} data-slot="field-error" className="text-sm text-danger">
              {kindError}
            </p>
          ) : null}
        </div>
        <Field
          id={`${id}-name`}
          label={t("signUp.name")}
          description={t("signUp.nameHelp")}
          error={fieldErrorOf(state, fields.name)}
          required
        >
          <Input name={fields.name} autoComplete="organization" defaultValue={values.name} />
        </Field>
        <Field
          id={`${id}-display-name`}
          label={t("signUp.displayName")}
          description={t("signUp.displayNameHelp")}
          error={fieldErrorOf(state, fields.displayName)}
        >
          <Input name={fields.displayName} autoComplete="name" defaultValue={values.displayName} />
        </Field>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("signUp.pending") : t("signUp.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
