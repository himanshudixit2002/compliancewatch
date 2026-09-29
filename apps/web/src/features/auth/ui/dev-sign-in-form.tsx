"use client";

import { useActionState, useId, useState } from "react";
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

/**
 * The development sign-in: tenant kind, the roles that kind allows, a display name and an
 * optional tenant id. Validation messages come back from the server action per field; the
 * submit button is disabled and marked busy while the action runs.
 */
export function DevSignInForm({
  action,
  options,
  next,
  seededTenantId = null,
}: DevSignInFormProps) {
  const { fields } = options;
  const [state, formAction, pending] = useActionState(action, idleAction());
  const [kind, setKind] = useState(options.defaultKind);
  const [tenantId, setTenantId] = useState("");
  const id = useId();
  const rolesError = fieldErrorOf(state, fields.roles);
  const rolesErrorId = `${id}-roles-error`;
  const rolesHelpId = `${id}-roles-help`;
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? state.formErrors : undefined;

  return (
    <div data-slot="dev-sign-in" className="flex max-w-xl flex-col gap-6">
      <PageHeader title={t("signIn.title")} description={t("signIn.devIntro")} />
      <Banner tone="info">{t("signIn.devNotice")}</Banner>
      {problem ? (
        <ErrorState
          title={problem.title}
          detail={problem.detail}
          correlationId={problem.correlationId || undefined}
        />
      ) : null}
      {formErrors && formErrors.length > 0 ? (
        <Banner tone="danger" title={t("signIn.refused")}>
          <ul>
            {formErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      <form action={formAction} className="flex flex-col gap-5" data-slot="dev-sign-in-form">
        {next ? <input type="hidden" name={fields.next} value={next} /> : null}
        <Field
          id={`${id}-kind`}
          label={t("signIn.tenantKind")}
          error={fieldErrorOf(state, fields.tenantKind)}
        >
          <Select
            name={fields.tenantKind}
            options={options.kinds}
            value={kind}
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
                <Checkbox id={boxId} name={fields.roles} value={option.value} />
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
          <Input name={fields.displayName} autoComplete="off" maxLength={80} />
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
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("signIn.pending") : t("signIn.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
