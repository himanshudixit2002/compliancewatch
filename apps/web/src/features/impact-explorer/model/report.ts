import type { DryRunReport } from "@/entities/applicability/types";
import { attributeOf } from "@/entities/ontology/mappers";
import type { Ontology } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { LOCALE, formatDateTime } from "@/shared/lib/dates";
import { levelLabel } from "@/shared/ui/applicability";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import type { CountView, DryRunReportView } from "../ui/dry-run-shared";

/**
 * A dry run's report in words: what was run over which businesses, the counts by result with their
 * share of the businesses decided, the attributes that decided the results (each named by key with
 * the ontology's meaning of it), and the sample decisions with every condition's outcome as the
 * engine describes it. Nothing in it is stored.
 */
const COUNT = new Intl.NumberFormat(LOCALE);

function count(value: number): string {
  return COUNT.format(value);
}

function share(value: number, of: number): string | null {
  if (of === 0) return null;
  return t("impact.report.share", { percent: Math.round((value / of) * 100) });
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function dryRunView(report: DryRunReport, ontology: Ontology | null): DryRunReportView {
  const definition = (attribute: string): string | null =>
    ontology === null ? null : (attributeOf(ontology, attribute)?.definition ?? null);
  const counts: CountView[] = [
    {
      key: "applies",
      label: t("applicability.applies"),
      value: count(report.counts.applies),
      share: share(report.counts.applies, report.evaluated),
    },
    {
      key: "not_applicable",
      label: t("applicability.notApplicable"),
      value: count(report.counts.notApplicable),
      share: share(report.counts.notApplicable, report.evaluated),
    },
    {
      key: "unsure",
      label: t("applicability.unsure"),
      value: count(report.counts.unsure),
      share: share(report.counts.unsure, report.evaluated),
    },
    {
      key: "needs_review",
      label: t("impact.report.needsReview"),
      value: count(report.needsReview),
      share: share(report.needsReview, report.evaluated),
    },
  ];
  return {
    subject:
      report.ruleVersionId === null
        ? t("impact.report.specification")
        : report.ruleKey === null || report.status === null
          ? report.ruleVersionId
          : t("impact.report.version", {
              rule: report.ruleKey,
              status: ruleVersionStatusLabel(report.status),
            }),
    scope:
      report.tenantId === null
        ? t("impact.report.everyTenant")
        : t("impact.report.oneTenant", { tenant: report.tenantId }),
    level: levelLabel(report.level),
    year: report.asOfFy,
    ranAt: formatDateTime(report.ranAt),
    nothingInScope: report.businessesTotal === 0,
    facts: {
      inScope: count(report.businessesTotal),
      evaluated: count(report.evaluated),
      skipped: count(report.skipped),
      max: count(report.maxBusinesses),
    },
    counts,
    byAttribute: report.byAttribute.map((row) => ({
      attribute: row.attribute,
      definition: definition(row.attribute),
      applies: count(row.applies),
      notApplicable: count(row.notApplicable),
      unsure: count(row.unsure),
    })),
    samples: report.samples.map((sample) => ({
      businessId: sample.businessId,
      tenantId: sample.tenantId,
      result: sample.result,
      needsReview: sample.needsReview,
      confidence: percent(sample.confidence),
      deciding: sample.deciding,
      conditions: sample.evaluated.map((predicate) => ({
        attribute: predicate.attribute,
        description: predicate.description,
        outcome: predicate.outcome,
        reason: predicate.reason,
      })),
    })),
  };
}
