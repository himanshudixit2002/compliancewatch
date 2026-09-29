"use client";

import { useActionState, useEffect, useId, useRef, useState } from "react";
import {
  Banner,
  Button,
  Checkbox,
  ErrorState,
  Field,
  Input,
  Label,
  PageHeader,
  Select,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type SignInAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

/** The options the page builds with `signInFormOptions()`; structural, so nothing is imported. */
export interface DevSignInFormOptions {
  fields: {
    tenantKind: string;
    roles: string;
    displayName: string;
    tenantId: string;
    next: string;
  };
  defaultKind: string;
  kinds: readonly { value: string; label: string }[];
  rolesByKind: Readonly<Record<string, readonly { value: string; label: string }[]>>;
}

export interface DevSignInFormProps {
  /** The server action; the page passes it so this client component imports no server code. */
  action: SignInAction;
  options: DevSignInFormOptions;
  /** The same-origin path to return to after signing in. */
  next?: string;
  /** The tenant the seed script filled last, offered as a one-click value. */
  seededTenantId?: string | null;
}

/** What a submit carried, so a refused submit shows the form as the visitor sent it. */
export interface SignInFormValues {
  tenantKind: string;
  roles: readonly string[];
  displayName: string;
  tenantId: string;
}

interface Attempt {
  state: ActionState;
  values: SignInFormValues;
  /** Submits so far. The fields remount on each one, from the values it carried. */
  count: number;
}

function textOf(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value : "";
}

/** Reads the submitted values back from the form data, by the form's input names. */
export function submittedValues(
  formData: FormData,
  fields: DevSignInFormOptions["fields"],
): SignInFormValues {
  return {
    tenantKind: textOf(formData.get(fields.tenantKind)),
    roles: formData.getAll(fields.roles).filter((role) => typeof role === "string"),
    displayName: textOf(formData.get(fields.displayName)),
    tenantId: textOf(formData.get(fields.tenantId)),
  };
}

/**
 * The development sign-in: tenant kind, the roles that kind allows, a display name and an
 * optional tenant id. Validation messages come back from the server action per field; the
 * submit button is disabled and marked busy while the action runs.
 *
 * React resets a form's uncontrolled fields after its action returns, and a controlled select
 * keeps its state while the reset moves the element back to its first option, so a refused
 * submit would lose what was typed and show one tenant kind while offering another kind's
 * roles. Each submit therefore records the values it carried, and the fields remount from them
 * as defaults (a remount per submit, keyed by the count): the kind, its roles, the checked
 * boxes, the name and the tenant id all come back as sent, from one source. After a refused
 * submit, focus moves to the error summary so a keyboard or screen-reader user hears why.
 */
export function DevSignInForm({
  action,
  options,
  next,
  seededTenantId = null,
}: DevSignInFormProps) {
  const { fields } = options;
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: submittedValues(formData, fields),
      count: previous.count + 1,
    }),
    {
      state: idleAction(),
      values: { tenantKind: options.defaultKind, roles: [], displayName: "", tenantId: "" },
      count: 0,
    },
  );
  const { state } = attempt;
  const errorsRef = useRef<HTMLDivElement>(null);
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") errorsRef.current?.focus();
  }, [attempt]);

  return (
    <div data-slot="dev-sign-in" className="flex max-w-xl flex-col gap-6">
      <PageHeader title={t("signIn.title")} description={t("signIn.devIntro")} />
      <Banner tone="info">{t("signIn.devNotice")}</Banner>
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="sign-in-errors"
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
            <Banner tone="danger" title={t("signIn.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!problem && formErrors.length === 0 ? (
            <Banner tone="danger" title={t("signIn.refused")}>
              {t("signIn.checkFields")}
            </Banner>
          ) : null}
        </div>
      ) : null}
      <form action={formAction} className="flex flex-col gap-5" data-slot="dev-sign-in-form">
        {next ? <input type="hidden" name={fields.next} value={next} /> : null}
        <SignInFields
          key={attempt.count}
          options={options}
          initial={attempt.values}
          state={state}
          seededTenantId={seededTenantId}
        />
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("signIn.pending") : t("signIn.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}

interface SignInFieldsProps {
  options: DevSignInFormOptions;
  /** The values of the last submit, or the empty form: every field's default. */
  initial: SignInFormValues;
  state: ActionState;
  seededTenantId: string | null;
}

/** The inputs, uncontrolled from `initial` except the tenant id, which a button can fill. */
function SignInFields({ options, initial, state, seededTenantId }: SignInFieldsProps) {
  const { fields } = options;
  const initialKind = options.kinds.some((kind) => kind.value === initial.tenantKind)
    ? initial.tenantKind
    : options.defaultKind;
  const [kind, setKind] = useState(initialKind);
  const [tenantId, setTenantId] = useState(initial.tenantId);
  const id = useId();
  const rolesError = fieldErrorOf(state, fields.roles);
  const rolesErrorId = `${id}-roles-error`;
  const rolesHelpId = `${id}-roles-help`;

  return (
    <>
      <Field
        id={`${id}-kind`}
        label={t("signIn.tenantKind")}
        error={fieldErrorOf(state, fields.tenantKind)}
      >
        <Select
          name={fields.tenantKind}
          options={options.kinds}
          defaultValue={initialKind}
          onChange={(event) => setKind(event.target.value)}
        />
      </Field>
      <fieldset
        className="grid gap-2"
        data-slot="roles"
        aria-describedby={[rolesHelpId, rolesError ? rolesErrorId : undefined]
          .filter(Boolean)
          .join(" ")}
        aria-invalid={rolesError ? true : undefined}
      >
        <legend className="text-sm font-medium text-fg">{t("signIn.roles")}</legend>
        <p id={rolesHelpId} className="text-sm text-fg-muted">
          {t("signIn.rolesHelp")}
        </p>
        {(options.rolesByKind[kind] ?? []).map((option) => {
          const boxId = `${id}-role-${option.value}`;
          return (
            <div key={option.value} className="flex items-center gap-2">
              <Checkbox
                id={boxId}
                name={fields.roles}
                value={option.value}
                defaultChecked={initial.roles.includes(option.value)}
              />
              <Label htmlFor={boxId}>{option.label}</Label>
            </div>
          );
        })}
        {rolesError ? (
          <p id={rolesErrorId} data-slot="field-error" className="text-sm text-danger">
            {rolesError}
          </p>
        ) : null}
      </fieldset>
      <Field
        id={`${id}-name`}
        label={t("signIn.displayName")}
        error={fieldErrorOf(state, fields.displayName)}
      >
        <Input
          name={fields.displayName}
          autoComplete="off"
          maxLength={80}
          defaultValue={initial.displayName}
        />
      </Field>
      <Field
        id={`${id}-tenant`}
        label={t("signIn.tenantId")}
        description={t("signIn.tenantIdHelp")}
        error={fieldErrorOf(state, fields.tenantId)}
      >
        <Input
          name={fields.tenantId}
          autoComplete="off"
          value={tenantId}
          onChange={(event) => setTenantId(event.target.value)}
        />
      </Field>
      {seededTenantId ? (
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setTenantId(seededTenantId)}
          >
            {t("signIn.useSeeded")}
          </Button>
        </div>
      ) : null}
    </>
  );
}
