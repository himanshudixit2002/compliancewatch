"use client";

import {
  startTransition,
  useActionState,
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { Banner, Button, ErrorState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction, type ActionState } from "@/shared/lib/action-state";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";

/**
 * A write sent from a client panel and what it came to, for the tools whose writes keep their
 * request (the pipeline's): the last answer, the request it answered, and a request whose answer
 * never arrived (a dropped connection, a server that did not respond), kept whole so "Try again"
 * sends exactly it, an Idempotency-Key included; a form's next request keeps the key of one still
 * open (`idempotencyKeyFor`). Focus moves to the outcome once it is known, since the dialog that
 * sent the request has closed and the busy button lost the focus.
 */
export type WriteAction<T> = (state: ActionState<T>, formData: FormData) => Promise<ActionState<T>>;

export interface WriteAttempt<T> {
  last: ActionState<T>;
  /** The request the last answer (or the lack of one) belongs to. */
  sent: FormData | null;
  /** The request whose answer never arrived. */
  lost: FormData | null;
  count: number;
}

/** A redirect or another error Next handles itself, which a form must let through. */
function isFrameworkError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("digest" in error)) return false;
  return String((error as { digest: unknown }).digest).startsWith("NEXT_");
}

export function useWriteAction<T>(action: WriteAction<T>) {
  const [attempt, dispatch, pending] = useActionState(
    async (previous: WriteAttempt<T>, formData: FormData): Promise<WriteAttempt<T>> => {
      try {
        const last = await action(idleAction(), formData);
        return { last, sent: formData, lost: null, count: previous.count + 1 };
      } catch (error) {
        if (isFrameworkError(error)) throw error;
        return { last: previous.last, sent: formData, lost: formData, count: previous.count + 1 };
      }
    },
    { last: idleAction<T>(), sent: null, lost: null, count: 0 },
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (attempt.count > 0) outcomeRef.current?.focus();
  }, [attempt]);
  const send = (formData: FormData) => startTransition(() => dispatch(formData));
  return { attempt, send, pending, outcomeRef };
}

/**
 * The Idempotency-Key a form's next request carries. While the last request is open (no answer
 * came, or the service recorded it and asks for the same request again, as `resendable` says),
 * its own key: the page renders again after such an answer and mints a new key, and a request
 * sent with that one would be a second request, leaving the first never finished. Once an answer
 * settles it (a success, or a refusal the same request cannot mend), the key the latest render
 * minted.
 */
export function idempotencyKeyFor<T>(
  attempt: WriteAttempt<T>,
  rendered: string,
  resendable: (problemType: string) => boolean,
): string {
  const { last, lost, sent } = attempt;
  const open =
    lost !== null ||
    (last.status === "error" && last.problem !== undefined && resendable(last.problem.type));
  const key = sent?.get(IDEMPOTENCY_KEY_FIELD);
  return open && typeof key === "string" && key !== "" ? key : rendered;
}

export interface WriteOutcomeProps<T> {
  attempt: WriteAttempt<T>;
  pending: boolean;
  /** Sends a request again as it was sent. */
  onResend: (formData: FormData) => void;
  outcomeRef: RefObject<HTMLDivElement | null>;
  /** A data-slot for the region, so a page with several panels tells them apart. */
  slot: string;
  /** Fields whose messages show under themselves, so they are not said twice. */
  fieldNames?: readonly string[];
  /** What a success shows; the announced message by default. */
  renderValue?: (value: T, message: string) => ReactNode;
  /**
   * A refusal the same request may still mend (the service recorded it and only a dependency
   * did not answer): it offers "Send the same request again" under the problem.
   */
  resendable?: (problemType: string) => boolean;
}

/**
 * What a write came to, where focus lands: the answer, its refusal with the correlation id, the
 * form's own messages, or that no answer arrived with "Try again".
 */
export function WriteOutcome<T>({
  attempt,
  pending,
  onResend,
  outcomeRef,
  slot,
  fieldNames = [],
  renderValue,
  resendable,
}: WriteOutcomeProps<T>) {
  const { last, lost, sent } = attempt;
  const messages =
    last.status === "error"
      ? [
          ...(last.formErrors ?? []),
          ...Object.entries(last.fieldErrors ?? {})
            .filter(([field]) => !fieldNames.includes(field))
            .flatMap(([, list]) => [...list]),
        ]
      : [];
  const again =
    last.status === "error" &&
    last.problem !== undefined &&
    sent !== null &&
    resendable?.(last.problem.type) === true;
  return (
    <div
      ref={outcomeRef}
      tabIndex={-1}
      data-slot={slot}
      className="flex flex-col gap-2 outline-none"
    >
      {lost !== null ? (
        <Banner
          tone="warning"
          title={t("writes.lostTitle")}
          data-slot="write-lost"
          action={
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={pending}
              aria-busy={pending || undefined}
              onClick={() => onResend(lost)}
            >
              {t("writes.tryAgain")}
            </Button>
          }
        >
          {t("writes.lostBody")}
        </Banner>
      ) : last.status === "ok" ? (
        <div role="status" data-slot="write-done" className="text-sm font-medium text-fg">
          {renderValue !== undefined && last.value !== undefined
            ? renderValue(last.value, last.message ?? "")
            : (last.message ?? "")}
        </div>
      ) : last.status === "error" ? (
        <>
          {last.problem === undefined ? null : (
            <ErrorState
              title={last.problem.title}
              detail={last.problem.detail}
              correlationId={last.problem.correlationId || undefined}
              data-problem={last.problem.type}
            />
          )}
          {again ? (
            <div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={pending}
                aria-busy={pending || undefined}
                onClick={() => onResend(sent)}
                data-slot="write-resend"
              >
                {t("writes.sendAgain")}
              </Button>
            </div>
          ) : null}
          {messages.map((message, index) => (
            <p key={index} role="alert" className="text-sm text-danger">
              {message}
            </p>
          ))}
        </>
      ) : null}
    </div>
  );
}
