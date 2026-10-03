"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface ConfirmActionProps {
  /** A server action; it receives `fields` as form data once the dialog is confirmed. */
  action: (formData: FormData) => Promise<void>;
  /** What the action is told, field name to value, such as the key's id. */
  fields: Readonly<Record<string, string>>;
  /** The button's visible word ("Revoke"). */
  label: string;
  /** What the action applies to ("CI deploy"); screen readers hear it after the label. */
  subject: string;
  title: string;
  /** Says exactly what happens once confirmed. */
  description: string;
  confirmLabel: string;
}

/**
 * A row action that cannot be undone, behind a confirm dialog: nothing is sent until the dialog
 * is confirmed, the buttons are disabled while the action runs, and the dialog closes when it is
 * done (the page then shows the new state).
 */
export function ConfirmAction({
  action,
  fields,
  label,
  subject,
  title,
  description,
  confirmLabel,
}: ConfirmActionProps) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  const confirm = () => {
    const formData = new FormData();
    for (const [name, value] of Object.entries(fields)) formData.set(name, value);
    startTransition(async () => {
      await action(formData);
      setOpen(false);
    });
  };

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button variant="ghost" size="sm">
          {label} <span className="sr-only">{subject}</span>
        </Button>
      }
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      cancelLabel={t("common.cancel")}
      destructive
      pending={pending}
      onConfirm={confirm}
    />
  );
}
