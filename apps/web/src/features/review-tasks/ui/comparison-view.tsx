import { t } from "@/shared/i18n";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import type { Comparison } from "../model/diff";

export interface ComparisonsProps {
  proposal: Comparison | null;
  previous: Comparison | null;
  previousError: ServiceErrorLike | null;
  /** The task has a draft to compare. */
  drafted: boolean;
}

const MARKS = { same: " ", removed: "-", added: "+" } as const;

function ComparisonBlock({ comparison, slot }: { comparison: Comparison; slot: string }) {
  return (
    <div className="flex flex-col gap-3" data-slot={slot}>
      <h3 className="text-base font-semibold text-fg">{comparison.title}</h3>
      {comparison.changed.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("workbench.diff.noChange")}</p>
      ) : (
        comparison.changed.map((field) => (
          <div key={field.field} className="flex flex-col gap-1" data-field={field.field}>
            <p className="text-sm font-medium text-fg">{field.label}</p>
            <ul
              className="flex flex-col rounded-md border bg-surface font-mono text-xs"
              aria-label={t("workbench.diff.linesLabel", {
                field: field.label,
                before: comparison.beforeLabel,
                after: comparison.afterLabel,
              })}
            >
              {field.lines.map((line, index) => (
                <li
                  key={index}
                  data-change={line.kind}
                  className={
                    line.kind === "added"
                      ? "border-l-4 border-l-success bg-success/10 px-2 py-0.5 whitespace-pre-wrap text-fg"
                      : line.kind === "removed"
                        ? "border-l-4 border-l-danger bg-danger/10 px-2 py-0.5 whitespace-pre-wrap text-fg"
                        : "border-l-4 border-l-transparent px-2 py-0.5 whitespace-pre-wrap text-fg-muted"
                  }
                >
                  <span aria-hidden="true">{MARKS[line.kind]} </span>
                  {line.kind === "same" ? null : (
                    <span className="sr-only">
                      {line.kind === "added"
                        ? t("workbench.diff.addedIn", { side: comparison.afterLabel })
                        : t("workbench.diff.removedFrom", { side: comparison.beforeLabel })}{" "}
                    </span>
                  )}
                  {line.text}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      {comparison.same.length === 0 ? null : (
        <p className="text-xs text-fg-muted">
          {t("workbench.diff.unchanged", { fields: comparison.same.join(", ") })}
        </p>
      )}
    </div>
  );
}

/**
 * What changed, field by field: the candidate's proposal against the draft made of it, and the
 * rule's previous version against this draft. A removed line is marked "-" and an added one "+",
 * with the change also said in words for a screen reader, so colour is never the only sign.
 */
export function Comparisons({ proposal, previous, previousError, drafted }: ComparisonsProps) {
  return (
    <section
      aria-labelledby="workbench-diff"
      data-slot="comparisons"
      className="flex flex-col gap-4"
    >
      <h2 id="workbench-diff" className="text-lg font-semibold text-fg">
        {t("workbench.diff.heading")}
      </h2>
      {!drafted ? (
        <p className="text-sm text-fg-muted" data-slot="diff-none">
          {t("workbench.diff.notDrafted")}
        </p>
      ) : (
        <>
          {proposal === null ? null : (
            <ComparisonBlock comparison={proposal} slot="diff-proposal" />
          )}
          {previousError === null ? null : <ServiceError error={previousError} />}
          {previous === null ? (
            previousError === null ? (
              <p className="text-sm text-fg-muted" data-slot="diff-no-previous">
                {t("workbench.diff.noPrevious")}
              </p>
            ) : null
          ) : (
            <ComparisonBlock comparison={previous} slot="diff-previous" />
          )}
        </>
      )}
    </section>
  );
}
