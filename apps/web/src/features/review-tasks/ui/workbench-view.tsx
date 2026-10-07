import type { Route } from "next";
import Link from "next/link";
import { Badge, KeyValue, PageHeader, StatusChip, cn } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RuleVersionStatusChip } from "@/shared/ui/rule-version-status";
import { ServiceError } from "@/shared/ui/service-error";
import type { WorkbenchView as WorkbenchModel } from "../model/workbench";
import { CandidatePane } from "./candidate-pane";
import { Comparisons } from "./comparison-view";
import { HistoryView } from "./history-view";
import { RulePane, type RuleActions } from "./rule-pane";
import { SourcePane } from "./source-pane";
import { PersonName } from "./write-result";

export interface WorkbenchViewProps {
  crumbs: readonly Crumb[];
  view: WorkbenchModel;
  /** The bound review steps; null when the session may not send any. */
  actions: RuleActions | null;
}

const TONES = { open: "warning", claimed: "info", decided: "success" } as const;

/**
 * The review workbench of one task: the facts of the task, then three panes side by side on a
 * wide screen and stacked on a narrow one (the source the draft rests on, a candidate task's
 * candidate, and the rule with the steps the task's state allows), then what changed and the
 * history. Every fact comes from the rulebook's task read and the reads it leads to.
 */
export function WorkbenchView({ crumbs, view, actions }: WorkbenchViewProps) {
  const facts = view.facts;
  const withCandidate = view.candidate !== null;
  return (
    <div data-slot="review-workbench" data-task={view.taskId} className="flex flex-col gap-8">
      <PageHeader
        title={view.title}
        description={view.candidateTask ? t("workbench.introCandidate") : t("workbench.introSeed")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <KeyValue
        data-slot="task-facts"
        items={[
          { key: "kind", label: t("workbench.fact.kind"), value: facts.kind },
          {
            key: "status",
            label: t("workbench.fact.status"),
            value: (
              <StatusChip
                status={facts.statusValue}
                tone={TONES[facts.statusValue as keyof typeof TONES] ?? "neutral"}
                label={facts.status}
              />
            ),
          },
          { key: "regulator", label: t("workbench.fact.regulator"), value: facts.regulator },
          { key: "priority", label: t("workbench.fact.priority"), value: String(facts.priority) },
          { key: "opened", label: t("workbench.fact.opened"), value: facts.opened },
          {
            key: "claimed",
            label: t("workbench.fact.claimed"),
            value:
              facts.claimed === null ? (
                t("reviewQueue.unclaimed")
              ) : (
                <span>
                  <PersonName person={facts.claimed.by} />
                  {facts.claimed.at === null ? null : `, ${facts.claimed.at}`}
                </span>
              ),
          },
          ...(facts.decision === null
            ? []
            : [
                {
                  key: "decision",
                  label: t("workbench.fact.decision"),
                  value: (
                    <span className="flex flex-col gap-0.5">
                      <span>
                        {facts.decision.label}
                        {facts.decision.by === null ? null : (
                          <>
                            {" "}
                            {t("reviewQueue.by")} <PersonName person={facts.decision.by} />
                          </>
                        )}
                        {facts.decision.at === null ? null : `, ${facts.decision.at}`}
                      </span>
                      {facts.decision.note === "" ? null : (
                        <span className="text-xs whitespace-pre-wrap text-fg-muted">
                          {facts.decision.note}
                        </span>
                      )}
                    </span>
                  ),
                },
              ]),
          {
            key: "version",
            label: t("workbench.fact.version"),
            value:
              facts.version === null ? (
                t("reviewQueue.notDrafted")
              ) : (
                <span className="flex flex-wrap items-center gap-2">
                  <Link
                    href={facts.version.href as Route}
                    className="font-mono text-sm text-primary underline-offset-2 hover:underline"
                  >
                    {facts.version.label}
                  </Link>
                  <RuleVersionStatusChip status={facts.version.status} />
                  {facts.version.highImpact ? (
                    <Badge tone="warning">{t("reviewQueue.highImpact")}</Badge>
                  ) : null}
                  {facts.version.closed ? (
                    <Badge tone="danger">{t("workbench.fact.closed")}</Badge>
                  ) : null}
                </span>
              ),
          },
        ]}
      />
      {view.ontologyError === null ? null : (
        <div className="flex flex-col gap-2" data-slot="ontology-missing">
          <p className="text-sm text-fg-muted">{t("workbench.ontologyMissing")}</p>
          <ServiceError error={view.ontologyError} />
        </div>
      )}
      <div
        className={cn(
          "grid grid-cols-1 gap-8 lg:grid-cols-2",
          withCandidate ? "2xl:grid-cols-3" : undefined,
        )}
        data-slot="panes"
      >
        <div className={cn("min-w-0", withCandidate ? "lg:row-span-2 2xl:row-span-1" : undefined)}>
          <SourcePane pane={view.source} />
        </div>
        {view.candidate === null ? null : (
          <div className="min-w-0">
            <CandidatePane pane={view.candidate} />
          </div>
        )}
        <div className="min-w-0">
          <RulePane
            pane={view.rule}
            candidateTask={view.candidateTask}
            access={view.access}
            ontology={view.editorOntology}
            actions={actions}
          />
        </div>
      </div>
      <Comparisons
        proposal={view.comparisons.proposal}
        previous={view.comparisons.previous}
        previousError={view.comparisons.previousError}
        drafted={view.facts.version !== null}
      />
      <HistoryView history={view.history} />
    </div>
  );
}
