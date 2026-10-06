"use client";

import type { RefObject } from "react";
import { ErrorState } from "@compliancewatch/ui";
import type { ControlAttempt } from "./use-control";

export interface ControlOutcomeProps {
  attempt: ControlAttempt;
  outcomeRef: RefObject<HTMLDivElement | null>;
  /** A data-slot for the region, so a page with several panels tells them apart. */
  slot: string;
}

/**
 * What a control came to, where focus lands: the sentence the action announced, or its refusal
 * (the engine's or the rulebook's problem with the correlation id to quote, or the form's own
 * check). Nothing before the first answer.
 */
export function ControlOutcome({ attempt, outcomeRef, slot }: ControlOutcomeProps) {
  const { last } = attempt;
  const messages =
    last.status === "error"
      ? [
          ...(last.formErrors ?? []),
          ...Object.values(last.fieldErrors ?? {}).flatMap((list) => [...list]),
        ]
      : [];
  return (
    <div
      ref={outcomeRef}
      tabIndex={-1}
      data-slot={slot}
      data-sent={attempt.sent ?? undefined}
      className="flex flex-col gap-2 outline-none"
    >
      {last.status === "ok" ? (
        <p role="status" className="text-sm font-medium text-fg" data-slot="control-done">
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
