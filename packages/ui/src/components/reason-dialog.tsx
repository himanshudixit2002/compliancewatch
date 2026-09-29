"use client";

import { useId, useState } from "react";
import { ConfirmDialog, type ConfirmDialogProps } from "./confirm-dialog";
import { Field } from "./field";
import { Textarea } from "./textarea";

export const REASON_MIN_LENGTH = 10;

export interface ReasonDialogProps extends Omit<
  ConfirmDialogProps,
  "onConfirm" | "children" | "confirmDisabled"
> {
  /** Label of the reason field. */
  label?: string;
  /** Explains what the reason is recorded against. */
  hint?: string;
  minLength?: number;
  onConfirm: (reason: string) => void | Promise<void>;
}

/**
 * ConfirmDialog with a required reason. Used only where the route takes a reason; the confirm
 * button stays disabled until the reason has at least ten characters.
 */
export function ReasonDialog({
  label = "Reason",
  hint,
  minLength = REASON_MIN_LENGTH,
  onConfirm,
  onOpenChange,
  ...props
}: ReasonDialogProps) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const trimmed = reason.trim();
  const tooShort = trimmed.length < minLength;
  const error = touched && tooShort ? `Enter at least ${minLength} characters.` : undefined;

  return (
    <ConfirmDialog
      {...props}
      onOpenChange={(open) => {
        if (!open) {
          setReason("");
          setTouched(false);
        }
        onOpenChange?.(open);
      }}
      confirmDisabled={tooShort}
      onConfirm={() => onConfirm(trimmed)}
    >
      <Field
        id={`${id}-reason`}
        label={label}
        required
        description={hint ?? `At least ${minLength} characters. ${trimmed.length}/${minLength}`}
        error={error}
      >
        <Textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          onBlur={() => setTouched(true)}
          data-slot="reason"
        />
      </Field>
    </ConfirmDialog>
  );
}
