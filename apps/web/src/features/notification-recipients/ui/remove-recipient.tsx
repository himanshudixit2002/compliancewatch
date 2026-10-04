"use client";

import { startTransition, useActionState, useRef, useState } from "react";
import { Banner, Button, ConfirmDialog, ErrorState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type RemoveRecipientAction = (
  state: ActionState,
  formData: FormData,
) => Promise<ActionState>;

export interface RemoveRecipientProps {
  action: RemoveRecipientAction;
  recipientId: string;
  /** The recipient's name, for the button's accessible name and the dialog. */
  name: string;
  returnBusiness: string;
  fields: { recipientId: string; returnBusiness: string };
}

/**
 * One recipient's Remove button and its confirm dialog, which says what the service deletes
 * (the recipient, its addresses and its business links) and what stays (each address's opt-in).
 * A removal returns to the page, which says so; a refused one keeps the dialog open with the
 * problem.
 */
export function RemoveRecipient({
  action,
  recipientId,
  name,
  returnBusiness,
  fields,
}: RemoveRecipientProps) {
  const formRef = useRef<HTMLFormElement>(null);
  const [open, setOpen] = useState(false);
  const [state, dispatch, pending] = useActionState(action, idleAction());
  const submit = () => {
    const form = formRef.current;
    if (form === null) return;
    const data = new FormData(form);
    startTransition(() => dispatch(data));
  };
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button variant="secondary" size="sm" aria-label={t("recipients.removeLabel", { name })}>
          {t("recipients.remove")}
        </Button>
      }
      title={t("recipients.removeTitle", { name })}
      description={t("recipients.removeBody")}
      confirmLabel={t("recipients.confirmRemove")}
      cancelLabel={t("common.cancel")}
      destructive
      pending={pending}
      onConfirm={submit}
    >
      <form
        ref={formRef}
        data-slot="remove-recipient-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <input type="hidden" name={fields.recipientId} value={recipientId} />
        <input type="hidden" name={fields.returnBusiness} value={returnBusiness} />
        {problem ? (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        ) : null}
        {formErrors.length > 0 ? (
          <Banner tone="danger" title={t("recipients.removeRefused")}>
            <ul>
              {formErrors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Banner>
        ) : null}
      </form>
    </ConfirmDialog>
  );
}
