"use client";

import { useActionState, useId, useState } from "react";
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Field, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type RejectDialogAction = (
  state: ActionState,
  formData: FormData,
) => Promise<ActionState>;

export interface RejectDialogProps {
  action: RejectDialogAction;
  triggerLabel: string;
  title: string;
  message?: string;
  candidateId?: string;
}

interface Attempt {
  state: ActionState;
}

export function RejectDialog({ action, triggerLabel, title, message, candidateId }: RejectDialogProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
    }),
    { state: idleAction() },
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent id={`${id}-dialog`}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form action={formAction} className="flex flex-col gap-4">
          {message !== undefined && (
            <p className="text-sm text-fg-muted">{message}</p>
          )}
          {candidateId !== undefined && (
            <input type="hidden" name="candidateId" value={candidateId} />
          )}
          <Field id={`${id}-reason`} label="Reason" required>
            <select id={`${id}-reason`} name="reason" className="w-full rounded-md border border-input px-3 py-2 text-sm">
              <option value="wrong_kind">Wrong relation kind</option>
              <option value="wrong_target">Wrong target</option>
              <option value="not_in_text">Not supported by text</option>
              <option value="duplicate">Duplicate</option>
              <option value="out_of_scope">Out of scope</option>
            </select>
          </Field>
          <Field id={`${id}-note`} label="Note">
            <Textarea id={`${id}-note`} name="note" rows={3} maxLength={2000} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending} variant="danger">
              {pending ? "Rejecting…" : "Reject"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
