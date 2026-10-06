"use client";

import type { RefObject } from "react";
import { Banner, Button, ErrorState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { TrackingAttempt } from "./tracking-form";

export interface TrackingOutcomeProps {
  attempt: TrackingAttempt;
  pending: boolean;
  /** Sends the lost request again, the same key with it. */
  onRetry: (formData: FormData) => void;
  outcomeRef: RefObject<HTMLDivElement | null>;
  /** Which messages a field already shows under itself, so they are not said twice. */
  fieldNames?: readonly string[];
}

/**
 * What a tracking write came to, announced where focus lands: the service's answer (a replay is
 * said in words), its refusal with the correlation id to quote, or that no answer arrived, with
 * "Try again" sending the same request, which the service records at most once.
 */
export function TrackingOutcome({
  attempt,
  pending,
  onRetry,
  outcomeRef,
  fieldNames = [],
}: TrackingOutcomeProps) {
  const { last, lost } = attempt;
  const formMessages =
    last.status === "error"
      ? [
          ...(last.formErrors ?? []),
          ...Object.entries(last.fieldErrors ?? {})
            .filter(([field]) => !fieldNames.includes(field))
            .flatMap(([, messages]) => [...messages]),
        ]
      : [];
  return (
    <div
      ref={outcomeRef}
      tabIndex={-1}
      data-slot="tracking-outcome"
      className="flex flex-col gap-2 outline-none"
    >
      {lost !== null ? (
        <Banner
          tone="warning"
          title={t("obligation.form.lostTitle")}
          action={
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={pending}
              aria-busy={pending || undefined}
              onClick={() => onRetry(lost)}
            >
              {t("obligation.form.retry")}
            </Button>
          }
        >
          {t("obligation.form.lostBody")}
        </Banner>
      ) : last.status === "ok" ? (
        <p role="status" className="text-sm font-medium text-fg" data-slot="tracking-done">
          {last.value?.message ?? last.message ?? ""}
        </p>
      ) : last.status === "error" ? (
        <>
          {last.problem === undefined ? null : (
            <ErrorState
              title={last.problem.title}
              detail={last.problem.detail}
              correlationId={last.problem.correlationId || undefined}
            />
          )}
          {formMessages.map((message, index) => (
            <p key={index} role="alert" className="text-sm text-danger">
              {message}
            </p>
          ))}
        </>
      ) : null}
    </div>
  );
}
