"use client";

import { startTransition, useId } from "react";
import { Button, Field, Input, Select } from "@compliancewatch/ui";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { t } from "@/shared/i18n";
import { ASSIGN_TO_ME, ASSIGN_TO_NOBODY, TRACKING_FIELDS } from "./tracking-shared";
import { useTrackingForm, type TrackingAction } from "./tracking-form";
import { TrackingOutcome } from "./tracking-outcome";

export interface AssigneeOption {
  id: string;
  label: string;
}

export type AssigneeMode =
  { kind: "members"; options: readonly AssigneeOption[] } | { kind: "id"; note: string };

export interface AssigneePanelProps {
  action: TrackingAction;
  businessId: string;
  obligationId: string;
  idempotencyKey: string;
  /** The user it is given to now; null for nobody. */
  assigneeId: string | null;
  /** How it is said: "You", a name, or the start of an id. */
  assigneeText: string;
  /** The signed-in user, for "Give it to me". */
  viewerId: string;
  mode: AssigneeMode;
  /** A closed obligation keeps its assignee. */
  open: boolean;
}

/**
 * Who the obligation is given to. A tenant admin picks one of the tenant's users as identity
 * lists them; anyone else, or anyone while identity cannot list them, gives it to themselves,
 * to nobody, or to a user by id (the page says why). With a verified token the obligation service
 * checks that the user belongs to the tenant; without one it keeps the id as named.
 */
export function AssigneePanel({
  action,
  businessId,
  obligationId,
  idempotencyKey,
  assigneeId,
  assigneeText,
  viewerId,
  mode,
  open,
}: AssigneePanelProps) {
  const id = useId();
  const { attempt, dispatch, pending, outcomeRef } = useTrackingForm(action);
  const fieldError =
    attempt.last.status === "error"
      ? attempt.last.fieldErrors?.[TRACKING_FIELDS.assignee]?.[0]
      : undefined;
  const retry = (formData: FormData) => startTransition(() => dispatch(formData));
  const hidden = (
    <>
      <input type="hidden" name={TRACKING_FIELDS.businessId} value={businessId} />
      <input type="hidden" name={TRACKING_FIELDS.obligationId} value={obligationId} />
      <input type="hidden" name={IDEMPOTENCY_KEY_FIELD} value={idempotencyKey} />
    </>
  );
  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="assignee-panel"
      className="flex flex-col gap-3"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("obligation.assignee.heading")}
      </h2>
      <p className="text-sm text-fg" data-slot="assignee-now">
        {assigneeId === null
          ? t("obligation.assignee.nobody")
          : t("obligation.assignee.now", { who: assigneeText })}
      </p>
      {!open ? (
        <p className="text-sm text-fg-muted">{t("obligation.assignee.closed")}</p>
      ) : mode.kind === "members" ? (
        <form
          action={dispatch}
          className="flex flex-wrap items-end gap-3"
          aria-label={t("obligation.assignee.form")}
        >
          {hidden}
          <Field
            id={`${id}-member`}
            label={t("obligation.assignee.member")}
            className="w-72"
            error={fieldError}
          >
            <Select
              key={assigneeId ?? ""}
              name={TRACKING_FIELDS.assignee}
              defaultValue={assigneeId ?? ""}
              options={[
                { value: "", label: t("obligation.assignee.nobodyOption") },
                ...mode.options.map((option) => ({ value: option.id, label: option.label })),
                ...(assigneeId !== null && !mode.options.some((option) => option.id === assigneeId)
                  ? [{ value: assigneeId, label: assigneeText }]
                  : []),
              ]}
            />
          </Field>
          <Button
            type="submit"
            variant="secondary"
            disabled={pending}
            aria-busy={pending || undefined}
          >
            {t("obligation.assignee.save")}
          </Button>
        </form>
      ) : (
        <form
          action={dispatch}
          className="flex flex-col gap-3"
          aria-label={t("obligation.assignee.form")}
        >
          {hidden}
          <p className="max-w-prose text-xs text-fg-muted">{mode.note}</p>
          <div className="flex flex-wrap items-end gap-3">
            <Field
              id={`${id}-user`}
              label={t("obligation.assignee.userId")}
              description={t("obligation.assignee.userIdHelp")}
              className="w-96"
              error={fieldError}
            >
              <Input
                key={assigneeId ?? ""}
                name={TRACKING_FIELDS.assignee}
                defaultValue={assigneeId ?? ""}
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
              />
            </Field>
            <Button
              type="submit"
              variant="secondary"
              disabled={pending}
              aria-busy={pending || undefined}
            >
              {t("obligation.assignee.save")}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              name={TRACKING_FIELDS.assignTo}
              value={ASSIGN_TO_ME}
              variant="secondary"
              size="sm"
              disabled={pending || assigneeId === viewerId}
            >
              {t("obligation.assignee.toMe")}
            </Button>
            <Button
              type="submit"
              name={TRACKING_FIELDS.assignTo}
              value={ASSIGN_TO_NOBODY}
              variant="ghost"
              size="sm"
              disabled={pending || assigneeId === null}
            >
              {t("obligation.assignee.clear")}
            </Button>
          </div>
        </form>
      )}
      <TrackingOutcome
        attempt={attempt}
        pending={pending}
        onRetry={retry}
        outcomeRef={outcomeRef}
        fieldNames={[TRACKING_FIELDS.assignee]}
      />
    </section>
  );
}
