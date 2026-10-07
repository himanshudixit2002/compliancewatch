import {
  Badge,
  Banner,
  KeyValue,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { SpecificationView } from "@/shared/ui/specification";
import type { CandidatePane as CandidatePaneModel } from "../model/candidate";
import { PersonName } from "./write-result";

export interface CandidatePaneProps {
  pane: CandidatePaneModel;
}

function Proposal({ pane }: CandidatePaneProps) {
  const proposal = pane.proposal;
  return (
    <div className="flex flex-col gap-3" data-slot="candidate-proposal">
      <h3 className="text-base font-semibold text-fg">
        {t("workbench.candidate.proposalHeading")}
      </h3>
      <KeyValue
        layout="stack"
        items={[
          {
            key: "title",
            label: t("workbench.diff.field.title"),
            value: proposal.title ?? t("workbench.diff.notStated"),
          },
          {
            key: "summary",
            label: t("workbench.diff.field.summary"),
            value: proposal.summary ?? t("workbench.diff.notStated"),
          },
          { key: "period", label: t("workbench.diff.field.period"), value: proposal.period },
          {
            key: "recurrence",
            label: t("workbench.diff.field.recurrence"),
            value: proposal.recurrence,
          },
          {
            key: "obligation",
            label: t("workbench.diff.field.template"),
            value:
              proposal.template === null ? (
                t("workbench.diff.notStated")
              ) : (
                <div className="flex flex-col gap-1">
                  <span className="font-medium">{proposal.template.title}</span>
                  {proposal.template.steps.length === 0 ? null : (
                    <ol className="ml-5 list-decimal">
                      {proposal.template.steps.map((step, index) => (
                        <li key={index}>{step}</li>
                      ))}
                    </ol>
                  )}
                  {proposal.template.due === null ? null : <span>{proposal.template.due}</span>}
                  <span>
                    {t("workbench.diff.evidence", { evidence: proposal.template.evidence })}
                  </span>
                </div>
              ),
          },
          {
            key: "condition",
            label: t("workbench.diff.field.specification"),
            value:
              proposal.specification === null ? (
                t("workbench.diff.notStated")
              ) : (
                <SpecificationView line={proposal.specification} />
              ),
          },
        ]}
      />
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium text-fg">{t("workbench.candidate.quotes")}</p>
        {proposal.citations.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("workbench.candidate.noQuotes")}</p>
        ) : (
          <ul className="flex flex-col gap-2" data-slot="candidate-quotes">
            {proposal.citations.map((citation, index) => (
              <li key={index} className="text-sm">
                <span className="text-xs text-fg-muted">
                  {t("workbench.source.clause", { ref: citation.clauseRef })}
                </span>
                <blockquote className="border-l-2 border-line-strong pl-3 whitespace-pre-wrap text-fg">
                  {citation.quote}
                </blockquote>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-1" data-slot="candidate-problems">
        <p className="text-sm font-medium text-fg">{t("workbench.candidate.problems")}</p>
        {proposal.problems.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("workbench.candidate.noProblems")}</p>
        ) : (
          <ul className="ml-5 list-disc text-sm text-fg">
            {proposal.problems.map((problem, index) => (
              <li key={index}>{problem}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * The candidate pane of a candidate task: the extraction's outcome, confidence, model and prompt,
 * whether it asked for review, the issues the validators found, why it looks high impact, the
 * rule key it suggests and whether a rule has it, and the draft it proposes field by field with
 * the problems mapping it. An unparseable candidate says plainly that there is none.
 */
export function CandidatePane({ pane }: CandidatePaneProps) {
  return (
    <section
      aria-labelledby="pane-candidate"
      data-slot="candidate-pane"
      className="flex min-w-0 flex-col gap-4"
    >
      <h2 id="pane-candidate" className="text-lg font-semibold text-fg">
        {t("workbench.candidate.heading")}
      </h2>
      {pane.unparseable ? (
        <Banner
          tone="warning"
          title={t("workbench.candidate.unparseableTitle")}
          data-slot="candidate-unparseable"
        >
          {t("workbench.candidate.unparseableBody")}
        </Banner>
      ) : null}
      <KeyValue
        data-slot="candidate-facts"
        items={[
          { key: "outcome", label: t("workbench.candidate.outcome"), value: pane.outcome },
          { key: "confidence", label: t("workbench.candidate.confidence"), value: pane.confidence },
          { key: "status", label: t("workbench.candidate.statusLabel"), value: pane.status },
          {
            key: "review",
            label: t("workbench.candidate.needsReview"),
            value: pane.needsReview ? t("workbench.yes") : t("workbench.no"),
          },
          {
            key: "model",
            label: t("workbench.candidate.model"),
            value: <code className="font-mono text-xs">{pane.model}</code>,
          },
          {
            key: "prompt",
            label: t("workbench.candidate.prompt"),
            value: <code className="font-mono text-xs">{pane.promptVersion}</code>,
          },
          {
            key: "quotes",
            label: t("workbench.candidate.citationCount"),
            value: String(pane.citationCount),
          },
          { key: "created", label: t("workbench.candidate.created"), value: pane.createdAt },
          ...pane.facts.map((fact, index) => ({
            key: `fact-${index}`,
            label: fact.label,
            value: fact.value,
          })),
          {
            key: "key",
            label: t("workbench.candidate.suggestedKey"),
            value:
              pane.suggestedKey === null ? (
                t("workbench.candidate.noKey")
              ) : (
                <span className="flex flex-col gap-1">
                  <code className="font-mono text-xs">{pane.suggestedKey}</code>
                  <span className="text-xs text-fg-muted">
                    {pane.suggestedKnown
                      ? t("workbench.candidate.keyKnown")
                      : t("workbench.candidate.keyUnknown")}
                  </span>
                </span>
              ),
          },
          {
            key: "impact",
            label: t("workbench.candidate.highImpact"),
            value: pane.highImpactSuggested ? (
              <span className="flex flex-col gap-1">
                <span>
                  <Badge tone="warning">{t("workbench.candidate.highImpactYes")}</Badge>
                </span>
                {pane.highImpactReasons.length === 0 ? null : (
                  <ul className="ml-5 list-disc text-sm" data-slot="high-impact-reasons">
                    {pane.highImpactReasons.map((reason, index) => (
                      <li key={index}>{reason}</li>
                    ))}
                  </ul>
                )}
              </span>
            ) : (
              t("workbench.no")
            ),
          },
          ...(pane.decided === null
            ? []
            : [
                {
                  key: "decided",
                  label: t("workbench.candidate.decided"),
                  value: (
                    <span>
                      {pane.decided.by === null ? null : <PersonName person={pane.decided.by} />}
                      {pane.decided.at === null ? null : ` ${pane.decided.at}`}
                      {pane.decided.reason === null ? null : ` (${pane.decided.reason})`}
                    </span>
                  ),
                },
              ]),
        ]}
      />
      <div className="flex flex-col gap-2" data-slot="candidate-issues">
        <h3 className="text-base font-semibold text-fg">
          {t("workbench.candidate.issuesHeading")}
        </h3>
        {pane.issues.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("workbench.candidate.noIssues")}</p>
        ) : (
          <Table scrollLabel={t("workbench.candidate.issuesRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("workbench.candidate.issuesCaption", { count: pane.issues.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("workbench.candidate.column.code")}</TableHead>
                <TableHead scope="col">{t("workbench.candidate.column.clause")}</TableHead>
                <TableHead scope="col">{t("workbench.candidate.column.detail")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pane.issues.map((issue, index) => (
                <TableRow key={index}>
                  <TableCell className="align-top">
                    <code className="font-mono text-xs">{issue.code}</code>
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    {issue.clauseRef ?? t("workbench.candidate.noClause")}
                  </TableCell>
                  <TableCell className="align-top text-sm">{issue.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      <Proposal pane={pane} />
    </section>
  );
}
