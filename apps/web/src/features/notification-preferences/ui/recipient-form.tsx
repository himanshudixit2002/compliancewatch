"use client";

import { useActionState, useId } from "react";
import { Button, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type RecipientAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface RecipientFormProps {
  action: RecipientAction;
  channel: string;
  /** "WhatsApp number", "Email address". */
  label: string;
  /** Names the form: "WhatsApp recipient". */
  formLabel: string;
  help: string;
  inputType: "tel" | "email";
  fields: { channel: string; recipient: string };
}

/**
 * Names the number or address whose preference the page shows. The value goes to the server
 * in the POST body, is checked there (the browser's own email check is off, so the message is
 * the same everywhere), and is remembered on this device; it never reaches a URL.
 */
export function RecipientForm({
  action,
  channel,
  label,
  formLabel,
  help,
  inputType,
  fields,
}: RecipientFormProps) {
  const id = useId();
  const [state, formAction, pending] = useActionState(action, idleAction());
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  return (
    <form
      action={formAction}
      aria-label={formLabel}
      noValidate
      data-slot="recipient-form"
      data-channel={channel}
      className="flex max-w-md flex-col gap-3"
    >
      <input type="hidden" name={fields.channel} value={channel} />
      <Field
        id={`${id}-recipient`}
        label={label}
        description={help}
        error={fieldErrorOf(state, fields.recipient) ?? formErrors[0]}
        required
      >
        <Input
          name={fields.recipient}
          type={inputType}
          inputMode={inputType}
          autoComplete={inputType === "tel" ? "tel" : "email"}
        />
      </Field>
      {problem ? (
        <ErrorState
          title={problem.title}
          detail={problem.detail}
          correlationId={problem.correlationId || undefined}
        />
      ) : null}
      <div>
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={pending}
          aria-busy={pending || undefined}
        >
          {pending ? t("notifications.lookingUp") : t("notifications.lookUp")}
        </Button>
      </div>
    </form>
  );
}
