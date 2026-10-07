import type { Route } from "next";
import Link from "next/link";
import {
  EmptyState,
  KeyValue,
  PageHeader,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { StatCard } from "@/shared/ui/stat-card";
import type { StatsView as StatsViewModel } from "../model/stats";

export interface StatsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The stats; null when they could not be read. */
  view: StatsViewModel | null;
  error?: ServiceErrorLike;
  queueHref: string;
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * The review queue in numbers, read-only and fresh on every visit: the tasks by status and by
 * regulator, how the decided ones were decided, the rule candidates analysts decided with the
 * acceptance rate explained, the median time to decide and how long the oldest open task waits.
 */
export function StatsView({ title, crumbs, view, error, queueHref }: StatsViewProps) {
  return (
    <div data-slot="review-stats" className="flex max-w-5xl flex-col gap-8">
      <PageHeader
        title={title}
        description={t("reviewStats.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={
          <Link
            href={queueHref as Route}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("reviewStats.toQueue")}
          </Link>
        }
      />
      {error !== undefined ? <ServiceError error={error} /> : null}
      {view === null ? null : (
        <>
          <Section id="stats-status" title={t("reviewStats.byStatusHeading")}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-slot="stats-status">
              <StatCard label={t("reviewStats.open")} value={view.byStatus.open} tone="warning" />
              <StatCard
                label={t("reviewStats.claimed")}
                value={view.byStatus.claimed}
                tone="info"
              />
              <StatCard
                label={t("reviewStats.decided")}
                value={view.byStatus.decided}
                tone="success"
              />
              <StatCard label={t("reviewStats.total")} value={view.byStatus.total} />
            </div>
          </Section>
          <Section id="stats-regulators" title={t("reviewStats.byRegulatorHeading")}>
            {view.regulators.length === 0 ? (
              <EmptyState
                title={t("reviewStats.noTasksTitle")}
                body={t("reviewStats.noTasksBody")}
              />
            ) : (
              <Table scrollLabel={t("reviewStats.regulatorsRegion")} data-slot="stats-regulators">
                <TableCaption className="text-left text-sm text-fg-muted">
                  {t("reviewStats.regulatorsCaption", { count: view.regulators.length })}
                </TableCaption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">{t("reviewStats.column.regulator")}</TableHead>
                    <TableHead scope="col">{t("reviewStats.open")}</TableHead>
                    <TableHead scope="col">{t("reviewStats.claimed")}</TableHead>
                    <TableHead scope="col">{t("reviewStats.decided")}</TableHead>
                    <TableHead scope="col">{t("reviewStats.total")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {view.regulators.map((row) => (
                    <TableRow key={row.regulator} data-regulator={row.regulator}>
                      <TableHead scope="row" className="font-medium">
                        {row.regulator}
                      </TableHead>
                      <TableCell>{row.open}</TableCell>
                      <TableCell>{row.claimed}</TableCell>
                      <TableCell>{row.decided}</TableCell>
                      <TableCell>{row.total}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>
          <Section id="stats-decisions" title={t("reviewStats.decisionsHeading")}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-slot="stats-decisions">
              <StatCard
                label={t("reviewStats.approved")}
                value={view.decisions.approved}
                tone="success"
              />
              <StatCard
                label={t("reviewStats.returned")}
                value={view.decisions.returned}
                tone="warning"
              />
              <StatCard
                label={t("reviewStats.rejected")}
                value={view.decisions.rejected}
                tone="danger"
              />
              <StatCard label={t("reviewStats.decisionsTotal")} value={view.decisions.total} />
            </div>
          </Section>
          <Section id="stats-candidates" title={t("reviewStats.candidatesHeading")}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-slot="stats-candidates">
              <StatCard
                label={t("reviewStats.candidatesDecided")}
                value={view.candidates.decided}
              />
              <StatCard
                label={t("reviewStats.approved")}
                value={view.candidates.approved}
                tone="success"
              />
              <StatCard
                label={t("reviewStats.approvedWithoutEdits")}
                value={view.candidates.approvedWithoutEdits}
                tone="success"
              />
              <StatCard
                label={t("reviewStats.rejected")}
                value={view.candidates.rejected}
                tone="danger"
              />
            </div>
            <div className="flex flex-col gap-1" data-slot="stats-acceptance">
              <p className="text-sm text-fg">
                <span className="font-medium">{t("reviewStats.acceptance")}: </span>
                {view.candidates.acceptance}
              </p>
              <p className="max-w-prose text-sm text-fg-muted">
                {view.candidates.explained ?? t("reviewStats.acceptanceWhy")}
              </p>
            </div>
          </Section>
          <Section id="stats-time" title={t("reviewStats.timeHeading")}>
            <KeyValue
              data-slot="stats-time"
              items={[
                { key: "median", label: t("reviewStats.median"), value: view.median },
                {
                  key: "oldest",
                  label: t("reviewStats.oldest"),
                  value:
                    view.oldestSince === null
                      ? view.oldest
                      : t("reviewStats.oldestSince", { age: view.oldest, since: view.oldestSince }),
                },
              ]}
            />
          </Section>
        </>
      )}
    </div>
  );
}
