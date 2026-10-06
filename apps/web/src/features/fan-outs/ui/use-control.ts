"use client";

import { startTransition, useActionState, useEffect, useRef } from "react";
import { idleAction, type ActionState } from "@/shared/lib/action-state";
import type { ControlResult } from "./controls-shared";

/** A fan-out control as its panel calls it: the server action, bound to the version or none. */
export type ControlAction = (
  state: ActionState<ControlResult>,
  formData: FormData,
) => Promise<ActionState<ControlResult>>;

export interface ControlAttempt {
  last: ActionState<ControlResult>;
  /** Which control the last answer was for, so the panel says it in the right place. */
  sent: string | null;
  count: number;
}

const START: ControlAttempt = { last: idleAction(), sent: null, count: 0 };

/**
 * useActionState over a control: remembers which control was sent and moves focus to the
 * outcome once the answer is known, since the dialog that sent it has closed and the busy button
 * lost the focus.
 */
export function useControl(action: ControlAction) {
  const [attempt, dispatch, pending] = useActionState(
    async (previous: ControlAttempt, formData: FormData): Promise<ControlAttempt> => {
      const sent = formData.get("sent");
      const last = await action(idleAction(), formData);
      return {
        last,
        sent: typeof sent === "string" ? sent : null,
        count: previous.count + 1,
      };
    },
    START,
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (attempt.count > 0) outcomeRef.current?.focus();
  }, [attempt]);
  const send = (sent: string, fields: Readonly<Record<string, string>>) => {
    const formData = new FormData();
    formData.set("sent", sent);
    for (const [name, value] of Object.entries(fields)) formData.set(name, value);
    startTransition(() => dispatch(formData));
  };
  return { attempt, send, pending, outcomeRef };
}
