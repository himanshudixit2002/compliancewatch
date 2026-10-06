"use client";

import { startTransition, useId, useState } from "react";
import { Button, ConfirmDialog, ReasonDialog } from "@compliancewatch/ui";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { t } from "@/shared/i18n";
import { TRACKING_FIELDS, WAIVER_MIN_LENGTH } from "./tracking-shared";
import { useTrackingForm, type TrackingAction } from "./tracking-form";
import { TrackingOutcome } from "./tracking-outcome";

export type StatusActionName = "start" | "complete" | "waive";

export interface StatusPanelProps {
  action: TrackingAction;
  businessId: string;
  obligationId: string;
  /** The Idempotency-Key this render minted for the status change. */
  idempotencyKey: string;
  /** The changes the obligation's status allows, with their labels. */
  actions: readonly { action: StatusActionName; label: string }[];
  title: string;
}

/**
 * Start, complete or waive the obligation. Starting needs no confirmation; completing closes it
 * for good, so a dialog says so first; waiving asks for the reason the history and the audit
 * keep (at least ten characters, the service's rule). Every request carries the key this render
 * minted, so a retry after a lost answer is recorded once.
 */
export function StatusPanel({
  action,
  businessId,
  obligationId,
  idempotencyKey,
  actions,
  title,
}: StatusPanelProps) {
  const id = useId();
  const [open, setOpen] = useState<StatusActionName | null>(null);
  const { attempt, dispatch, pending, outcomeRef } = useTrackingForm(action);

  const send = (name: StatusActionName, reason = "") => {
    const formData = new FormData();
    formData.set(TRACKING_FIELDS.businessId, businessId);
    formData.set(TRACKING_FIELDS.obligationId, obligationId);
    formData.set(TRACKING_FIELDS.action, name);
    formData.set(TRACKING_FIELDS.reason, reason);
    formData.set(IDEMPOTENCY_KEY_FIELD, idempotencyKey);
    setOpen(null);
    startTransition(() => dispatch(formData));
  };
  const retry = (formData: FormData) => startTransition(() => dispatch(formData));

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="status-panel"
      className="flex flex-col gap-3"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("obligation.status.heading")}
      </h2>
      {actions.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("obligation.status.closed")}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {actions.map((item) => (
            <Button
              key={item.action}
              type="button"
              data-action={item.action}
              variant={item.action === "complete" ? "primary" : "secondary"}
              disabled={pending}
              aria-busy={(pending && open === null) || undefined}
              onClick={() => (item.action === "start" ? send("start") : setOpen(item.action))}
            >
              {item.label}
            </Button>
          ))}
        </div>
      )}
      <TrackingOutcome
        attempt={attempt}
        pending={pending}
        onRetry={retry}
        outcomeRef={outcomeRef}
      />
      <ConfirmDialog
        open={open === "complete"}
        onOpenChange={(next) => setOpen(next ? "complete" : null)}
        title={t("obligation.complete.title")}
        description={t("obligation.complete.description", { title })}
        confirmLabel={t("obligation.complete.confirm")}
        cancelLabel={t("common.cancel")}
        pending={pending}
        onConfirm={() => send("complete")}
      />
      <ReasonDialog
        open={open === "waive"}
        onOpenChange={(next) => setOpen(next ? "waive" : null)}
        title={t("obligation.waive.title")}
        description={t("obligation.waive.description", { title })}
        label={t("obligation.waive.reason")}
        minLength={WAIVER_MIN_LENGTH}
        confirmLabel={t("obligation.waive.confirm")}
        cancelLabel={t("common.cancel")}
        destructive
        pending={pending}
        onConfirm={(reason) => send("waive", reason)}
      />
    </section>
  );
}
