"use client";

import { createContext, useContext, type ReactNode } from "react";
import { HighlightMark } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/**
 * The text of every clause the workbench shows, sent to the browser once: the source pane draws
 * each clause from it and the citation rows check a quote against it, so neither carries the text
 * again (a long document's clauses would otherwise travel twice, once as the pane's markup and
 * once with the form).
 */
const ClauseTexts = createContext<Readonly<Record<string, string>>>({});

export function ClauseTextsProvider({
  texts,
  children,
}: {
  /** Each clause's text by its id. */
  texts: Readonly<Record<string, string>>;
  children: ReactNode;
}) {
  return <ClauseTexts.Provider value={texts}>{children}</ClauseTexts.Provider>;
}

/** Every clause text the page holds, by clause id. */
export function useClauseTexts(): Readonly<Record<string, string>> {
  return useContext(ClauseTexts);
}

/** A run of a clause's text by its code points, `start` included and `end` not. */
export interface ClauseRun {
  start: number;
  end: number;
  /** A quote of the draft covers the run. */
  mark: boolean;
}

/** A clause's text in its runs, each one a quote covers highlighted. */
export function ClauseText({ clauseId, runs }: { clauseId: string; runs: readonly ClauseRun[] }) {
  const points = Array.from(useClauseTexts()[clauseId] ?? "");
  return (
    <>
      {runs.map((run, index) => {
        const text = points.slice(run.start, run.end).join("");
        return run.mark ? (
          <HighlightMark
            key={index}
            startLabel={t("workbench.source.markStart")}
            endLabel={t("workbench.source.markEnd")}
          >
            {text}
          </HighlightMark>
        ) : (
          <span key={index}>{text}</span>
        );
      })}
    </>
  );
}
