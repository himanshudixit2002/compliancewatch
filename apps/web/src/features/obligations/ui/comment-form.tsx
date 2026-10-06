"use client";

import { startTransition, useId } from "react";
import { Button, Field, Textarea } from "@compliancewatch/ui";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { t } from "@/shared/i18n";
import { TEXT_MAX_LENGTH, TRACKING_FIELDS } from "./tracking-shared";
import { useTrackingForm, type TrackingAction } from "./tracking-form";
import { TrackingOutcome } from "./tracking-outcome";

export interface CommentFormProps {
  action: TrackingAction;
  businessId: string;
  obligationId: string;
  idempotencyKey: string;
}

/**
 * A comment on the obligation, closed or not: 1 to 2000 characters, kept for good (the service
 * never changes or deletes one). The key this render minted makes a double submit one comment.
 */
export function CommentForm({
  action,
  businessId,
  obligationId,
  idempotencyKey,
}: CommentFormProps) {
  const id = useId();
  const { attempt, dispatch, pending, outcomeRef } = useTrackingForm(action);
  const fieldError =
    attempt.last.status === "error"
      ? attempt.last.fieldErrors?.[TRACKING_FIELDS.body]?.[0]
      : undefined;
  const retry = (formData: FormData) => startTransition(() => dispatch(formData));
  return (
    <div className="flex flex-col gap-3" data-slot="comment-form">
      <form
        action={dispatch}
        aria-label={t("obligation.comments.form")}
        className="flex flex-col gap-3"
      >
        <input type="hidden" name={TRACKING_FIELDS.businessId} value={businessId} />
        <input type="hidden" name={TRACKING_FIELDS.obligationId} value={obligationId} />
        <input type="hidden" name={IDEMPOTENCY_KEY_FIELD} value={idempotencyKey} />
        <Field
          id={`${id}-body`}
          label={t("obligation.comments.label")}
          description={t("obligation.comments.help", { max: TEXT_MAX_LENGTH })}
          error={fieldError}
        >
          <Textarea name={TRACKING_FIELDS.body} rows={3} maxLength={TEXT_MAX_LENGTH} />
        </Field>
        <div>
          <Button
            type="submit"
            variant="secondary"
            disabled={pending}
            aria-busy={pending || undefined}
          >
            {t("obligation.comments.submit")}
          </Button>
        </div>
      </form>
      <TrackingOutcome
        attempt={attempt}
        pending={pending}
        onRetry={retry}
        outcomeRef={outcomeRef}
        fieldNames={[TRACKING_FIELDS.body]}
      />
    </div>
  );
}
