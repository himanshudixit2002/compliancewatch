"use client";

import { useActionState, useEffect, useRef } from "react";
import { idleAction, type ActionState } from "@/shared/lib/action-state";
import type { TrackingResult } from "./tracking-shared";

/** A tracking write as its form calls it: the server action, bound to nothing. */
export type TrackingAction = (
  state: ActionState<TrackingResult>,
  formData: FormData,
) => Promise<ActionState<TrackingResult>>;

/**
 * Where a tracking form stands: the last answer, and the request whose answer never arrived (a
 * dropped connection, a server that did not respond). That request is kept whole, Idempotency-Key
 * included, so "Try again" sends exactly it: if the first one reached the service, the service
 * answers with its first answer instead of recording the change twice.
 */
export interface TrackingAttempt {
  last: ActionState<TrackingResult>;
  lost: FormData | null;
  count: number;
}

const START: TrackingAttempt = { last: idleAction(), lost: null, count: 0 };

/** A redirect or another error Next handles itself, which a form must let through. */
function isFrameworkError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("digest" in error)) return false;
  return String((error as { digest: unknown }).digest).startsWith("NEXT_");
}

/**
 * useActionState over a tracking action, keeping a lost request for its retry and moving focus to
 * the outcome once an answer (or the lack of one) is known, since the busy button lost it.
 */
export function useTrackingForm(action: TrackingAction) {
  const [attempt, dispatch, pending] = useActionState(
    async (previous: TrackingAttempt, formData: FormData): Promise<TrackingAttempt> => {
      try {
        const last = await action(idleAction(), formData);
        return { last, lost: null, count: previous.count + 1 };
      } catch (error) {
        if (isFrameworkError(error)) throw error;
        return { last: previous.last, lost: formData, count: previous.count + 1 };
      }
    },
    START,
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (attempt.count > 0) outcomeRef.current?.focus();
  }, [attempt]);
  return { attempt, dispatch, pending, outcomeRef };
}
