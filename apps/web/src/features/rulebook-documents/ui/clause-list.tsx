import { HighlightMark } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { ClauseView } from "../model/document-view";

export interface ClauseListProps {
  clauses: readonly ClauseView[];
}

function ClauseText({ clause }: { clause: ClauseView }) {
  if (clause.mark === "span" && clause.parts !== null) {
    return (
      <>
        {clause.parts.before}
        <HighlightMark startLabel={t("documents.mark.start")} endLabel={t("documents.mark.end")}>
          {clause.parts.mark}
        </HighlightMark>
        {clause.parts.after}
      </>
    );
  }
  if (clause.mark === "clause") {
    return (
      <HighlightMark startLabel={t("documents.mark.start")} endLabel={t("documents.mark.end")}>
        {clause.text}
      </HighlightMark>
    );
  }
  return <>{clause.text}</>;
}

/**
 * The clauses in reading order, each with its reference, its page and an anchor of its own
 * (`#clause-en.p3`, focusable so a jump lands there). The text is shown exactly as stored,
 * whitespace included, with the marked span or clause when a link asked for one.
 */
export function ClauseList({ clauses }: ClauseListProps) {
  return (
    <ol data-slot="clause-list" className="flex flex-col gap-4">
      {clauses.map((clause) => (
        <li
          key={clause.clauseId}
          id={clause.anchorId}
          tabIndex={-1}
          data-clause-ref={clause.clauseRef}
          data-marked={clause.mark ?? undefined}
          aria-labelledby={`${clause.anchorId}-heading`}
          className="scroll-mt-4 rounded-lg border bg-surface-raised p-4 outline-none focus-visible:ring-2 focus-visible:ring-focus/50 data-[marked]:border-warning"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id={`${clause.anchorId}-heading`} className="text-sm font-semibold text-fg">
              <a href={`#${clause.anchorId}`} className="hover:underline">
                {t("documents.clause.heading", { ref: clause.clauseRef })}
              </a>
            </h3>
            <p className="text-xs text-fg-muted" data-slot="clause-page">
              {clause.page === null
                ? t("documents.clause.noPage")
                : t("documents.clause.page", { page: clause.page })}
            </p>
          </div>
          <p className="mt-2 text-sm whitespace-pre-wrap text-fg" data-slot="clause-text">
            <ClauseText clause={clause} />
          </p>
        </li>
      ))}
    </ol>
  );
}
