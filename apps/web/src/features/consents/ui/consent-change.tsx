"use client";

import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import { Banner, Button, ConfirmDialog, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type ConsentChangeAction<R> = (
  state: ActionState<R>,
  formData: FormData,
) => Promise<ActionState<R>>;

export interface ConsentChangeProps<R> {
  action: ConsentChangeAction<R>;
  purpose: string;
  /** "WhatsApp reminders"; names the button and the dialog. */
  purposeLabel: string;
  change: "withdraw" | "give";
  /** The sentence the person confirms; the record keeps it inside its evidence. */
  statement: string;
  /** What the record carries, in words; the dialog's description. */
  records: string;
  /** WhatsApp reminders only: the number field, filled with the number this device remembers. */
  number?: { defaultValue: string; required: boolean; help: string };
  fields: { purpose: string; change: string; number: string };
}

/**
 * One purpose's give or withdraw button and its confirm dialog. The dialog says exactly what
 * the record will carry and shows the sentence being confirmed; for WhatsApp reminders it also
 * holds the number to opt in or out. The confirm button stays busy while the action runs; a
 * refused change keeps the dialog open with the problem and the field to fix, and a recorded
 * one closes it and says what was recorded in the status line under the button (the page then
 * shows the new record).
 */
export function ConsentChange<R>({
  action,
  purpose,
  purposeLabel,
  change,
  statement,
  records,
  number,
  fields,
}: ConsentChangeProps<R>) {
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const [open, setOpen] = useState(false);
  const [state, dispatch, pending] = useActionState(
    async (previous: ActionState<R>, formData: FormData): Promise<ActionState<R>> => {
      const next = await action(previous, formData);
      // A recorded change closes the dialog; a refused one keeps it open with the problem.
      if (next.status === "ok") setOpen(false);
      return next;
    },
    idleAction<R>(),
  );

  const submit = () => {
    const form = formRef.current;
    if (form === null) return;
    const data = new FormData(form);
    startTransition(() => dispatch(data));
  };

  // Once the page shows the new record the button flips (withdraw to give, or back): it is a
  // new element then, so it does not fade between the two looks, and focus moves to the status
  // line that says what was recorded instead of being lost with the old button.
  const statusRef = useRef<HTMLParagraphElement>(null);
  const shownChange = useRef(change);
  useEffect(() => {
    if (shownChange.current === change) return;
    shownChange.current = change;
    if (state.status === "ok") statusRef.current?.focus();
  }, [change, state.status]);

  const withdraw = change === "withdraw";
  // The visible word, with the purpose in the accessible name: a row of "Withdraw" buttons.
  const buttonLabel = withdraw ? t("consentSettings.withdraw") : t("consentSettings.give");
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const numberError = fieldErrorOf(state, fields.number);
  return (
    <div data-slot="consent-change" data-purpose={purpose} className="flex flex-col gap-1">
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        trigger={
          <Button
            key={change}
            variant={withdraw ? "secondary" : "primary"}
            size="sm"
            aria-label={`${buttonLabel}: ${purposeLabel}`}
          >
            {buttonLabel}
          </Button>
        }
        title={
          withdraw
            ? t("consentSettings.withdrawTitle", { purpose: purposeLabel })
            : t("consentSettings.giveTitle", { purpose: purposeLabel })
        }
        description={records}
        confirmLabel={
          withdraw ? t("consentSettings.confirmWithdraw") : t("consentSettings.confirmGive")
        }
        cancelLabel={t("common.cancel")}
        destructive={withdraw}
        pending={pending}
        onConfirm={submit}
      >
        <form
          ref={formRef}
          data-slot="consent-change-form"
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <input type="hidden" name={fields.purpose} value={purpose} />
          <input type="hidden" name={fields.change} value={change} />
          <blockquote className="border-l-2 border-line pl-3 text-sm text-fg">
            {statement}
          </blockquote>
          {number === undefined ? null : (
            <Field
              id={`${id}-number`}
              label={t("consentSettings.number")}
              description={number.help}
              error={numberError}
              required={number.required}
            >
              <Input
                name={fields.number}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                defaultValue={number.defaultValue}
              />
            </Field>
          )}
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
            />
          ) : null}
          {formErrors.length > 0 ? (
            <Banner tone="danger" title={t("consentSettings.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
        </form>
      </ConfirmDialog>
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        data-slot="consent-change-status"
        className="text-sm text-fg-muted outline-none"
      >
        {state.status === "ok" ? state.message : ""}
      </p>
    </div>
  );
}
