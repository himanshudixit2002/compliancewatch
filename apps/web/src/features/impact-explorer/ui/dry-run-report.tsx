import {
  EmptyState,
  KeyValue,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type KeyValueItem,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ApplicabilityBadge } from "@/shared/ui/applicability";
import { StatCard } from "@/shared/ui/stat-card";
import type { DryRunReportView } from "./dry-run-shared";

export interface DryRunReportProps {
  report: DryRunReportView;
}

const TONES = {
  applies: "success",
  not_applicable: "neutral",
  unsure: "warning",
  needs_review: "warning",
} as const;

/**
 * What a dry run found: what was run over which businesses, the counts by result (each with its
 * share of the businesses decided), the attributes that decided the results, and the sample
 * decisions with every condition's outcome. Nothing of it is stored.
 */
export function DryRunReport({ report }: DryRunReportProps) {
  const facts: KeyValueItem[] = [
    { key: "subject", label: t("impact.report.subjectLabel"), value: report.subject },
    { key: "scope", label: t("impact.report.scopeLabel"), value: report.scope },
    { key: "level", label: t("impact.report.levelLabel"), value: report.level },
    { key: "year", label: t("impact.report.yearLabel"), value: report.year },
    {
      key: "businesses",
      label: t("impact.report.businessesLabel"),
      value: t("impact.report.businesses", {
        inScope: report.facts.inScope,
        evaluated: report.facts.evaluated,
        skipped: report.facts.skipped,
      }),
    },
    { key: "max", label: t("impact.report.maxLabel"), value: report.facts.max },
    { key: "ran", label: t("impact.report.ranLabel"), value: report.ranAt },
  ];
  return (
    <section
      aria-labelledby="dry-run-report"
      data-slot="dry-run-report"
      className="flex flex-col gap-4"
    >
      <h2 id="dry-run-report" className="text-lg font-semibold text-fg">
        {t("impact.report.heading")}
      </h2>
      <KeyValue items={facts} aria-label={t("impact.report.factsLabel")} />
      {report.nothingInScope ? (
        <EmptyState title={t("impact.report.emptyTitle")} body={t("impact.report.emptyBody")} />
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-slot="dry-run-counts">
        {report.counts.map((item) => (
          <div key={item.key} data-count={item.key}>
            <StatCard
              label={item.label}
              value={item.value}
              tone={TONES[item.key]}
              hint={item.share ?? undefined}
            />
          </div>
        ))}
      </div>
      {report.byAttribute.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("impact.report.noAttributes")}</p>
      ) : (
        <Table scrollLabel={t("impact.report.attributesRegion")} data-slot="dry-run-attributes">
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("impact.report.attributesCaption")}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("impact.report.column.attribute")}</TableHead>
              <TableHead scope="col">{t("applicability.applies")}</TableHead>
              <TableHead scope="col">{t("applicability.notApplicable")}</TableHead>
              <TableHead scope="col">{t("applicability.unsure")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.byAttribute.map((row) => (
              <TableRow key={row.attribute} data-attribute={row.attribute}>
                <TableCell className="align-top whitespace-normal">
                  <code className="font-mono text-xs">{row.attribute}</code>
                  {row.definition === null ? null : (
                    <span className="block text-xs text-fg-muted">{row.definition}</span>
                  )}
                </TableCell>
                <TableCell className="align-top">{row.applies}</TableCell>
                <TableCell className="align-top">{row.notApplicable}</TableCell>
                <TableCell className="align-top">{row.unsure}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {report.samples.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("impact.report.noSamples")}</p>
      ) : (
        <Table scrollLabel={t("impact.report.samplesRegion")} data-slot="dry-run-samples">
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("impact.report.samplesCaption", { count: report.samples.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("impact.report.column.business")}</TableHead>
              <TableHead scope="col">{t("impact.report.column.result")}</TableHead>
              <TableHead scope="col">{t("impact.report.column.conditions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.samples.map((sample) => (
              <TableRow key={sample.businessId} data-sample={sample.businessId}>
                <TableCell className="align-top whitespace-normal">
                  <code className="block font-mono text-xs">{sample.businessId}</code>
                  <span className="block text-xs text-fg-muted">
                    {t("impact.report.tenantOf", { tenant: sample.tenantId })}
                  </span>
                </TableCell>
                <TableCell className="align-top">
                  <ApplicabilityBadge result={sample.result} needsReview={sample.needsReview} />
                  <span className="mt-1 block text-xs text-fg-muted">
                    {t("impact.report.confidence", { confidence: sample.confidence })}
                  </span>
                  {sample.deciding.length === 0 ? null : (
                    <span className="block text-xs text-fg-muted">
                      {t("impact.report.decidedBy", { attributes: sample.deciding.join(", ") })}
                    </span>
                  )}
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  <ul className="flex flex-col gap-1 text-sm">
                    {sample.conditions.map((condition, index) => (
                      <li key={`${condition.attribute}-${index}`}>
                        <span className="text-fg">{condition.description}</span>{" "}
                        <ApplicabilityBadge result={condition.outcome} />
                        <span className="block text-xs text-fg-muted">{condition.reason}</span>
                      </li>
                    ))}
                  </ul>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
