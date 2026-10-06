"use client";

import type { Route } from "next";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button, ErrorState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { FirstObligationState } from "./tracking-shared";

export interface FirstObligationPollProps {
  /** Asks the server for the business's first obligation (a server action bound to it). */
  check: () => Promise<FirstObligationState>;
  /** What the page read when it rendered; "found" needs no poll. */
  initial: FirstObligationState;
  listHref: string;
  /** Seconds between checks, and how long to keep checking before saying so. */
  intervalSeconds?: number;
  timeoutSeconds?: number;
}

type PollState =
  | { phase: "polling"; last: FirstObligationState }
  | { phase: "found"; found: Extract<FirstObligationState, { status: "found" }> }
  | { phase: "waited"; last: FirstObligationState };

function startFrom(initial: FirstObligationState): PollState {
  return initial.status === "found"
    ? { phase: "found", found: initial }
    : { phase: "polling", last: initial };
}

/**
 * The end of onboarding asks whether the business has its first obligation yet. Working out what
 * applies happens after the answers are stored (the profile change reaches the engine, which
 * decides each published rule, and the obligation service makes the obligations), so the page
 * checks every few seconds and says so while it does. It stops at the first obligation, or after
 * the timeout with an honest note that the work goes on and where to look later; "Check again"
 * starts over. A failed check is shown with its correlation id and the polling continues.
 */
export function FirstObligationPoll({
  check,
  initial,
  listHref,
  intervalSeconds = 3,
  timeoutSeconds = 90,
}: FirstObligationPollProps) {
  const id = useId();
  const [state, setState] = useState<PollState>(() => startFrom(initial));
  const [round, setRound] = useState(0);
  const checking = useRef(false);

  const tick = useCallback(async (): Promise<FirstObligationState | null> => {
    if (checking.current) return null;
    checking.current = true;
    try {
      return await check();
    } catch {
      return {
        status: "error",
        message: t("firstObligation.unreachable"),
        correlationId: null,
      };
    } finally {
      checking.current = false;
    }
  }, [check]);

  const polling = state.phase === "polling";
  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    const started = Date.now();
    const timer = setInterval(() => {
      void tick().then((answer) => {
        if (cancelled || answer === null) return;
        if (answer.status === "found") {
          setState({ phase: "found", found: answer });
        } else if (Date.now() - started >= timeoutSeconds * 1000) {
          setState({ phase: "waited", last: answer });
        } else {
          setState({ phase: "polling", last: answer });
        }
      });
    }, intervalSeconds * 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [polling, round, intervalSeconds, timeoutSeconds, tick]);

  const last = state.phase === "found" ? null : state.last;
  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="first-obligation"
      data-phase={state.phase}
      className="flex flex-col gap-3"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("firstObligation.heading")}
      </h2>
      <div role="status" className="flex flex-col gap-2 text-sm">
        {state.phase === "found" ? (
          <p>
            {t("firstObligation.found", { due: state.found.due })}{" "}
            <Link
              href={state.found.href as Route}
              className="font-medium text-primary underline underline-offset-2"
            >
              {state.found.title}
            </Link>
            {state.found.dueNote === null ? null : (
              <span className="text-fg-muted"> ({state.found.dueNote})</span>
            )}
          </p>
        ) : state.phase === "polling" ? (
          <p className="text-fg-muted">
            {t("firstObligation.looking", { seconds: intervalSeconds })}
          </p>
        ) : (
          <div data-slot="first-obligation-waited" className="flex flex-col gap-1">
            <p className="font-medium text-fg">{t("firstObligation.waitedTitle")}</p>
            <p className="max-w-prose text-fg-muted">
              {t("firstObligation.waitedBody", { seconds: timeoutSeconds })}
            </p>
          </div>
        )}
      </div>
      {last?.status === "error" ? (
        <ErrorState title={last.message} correlationId={last.correlationId ?? undefined} />
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        {state.phase === "waited" ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setState({ phase: "polling", last: state.last });
              setRound((value) => value + 1);
            }}
          >
            {t("firstObligation.checkAgain")}
          </Button>
        ) : null}
        <Link
          href={listHref as Route}
          className="text-sm text-primary underline-offset-2 hover:underline"
        >
          {t("firstObligation.list")}
        </Link>
      </div>
    </section>
  );
}
