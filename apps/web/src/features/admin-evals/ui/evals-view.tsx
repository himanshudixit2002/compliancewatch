import type { Route } from "next";
import Link from "next/link";
import {
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  evalSummary,
  runStatusLabel,
  runStatusTone,
  scorePercent,
  sortRuns,
  type EvalRun,
} from "../model/evals";

export interface AdminEvalsViewProps {
  runs: readonly EvalRun[];
  /** A run's own page; without it the run names are not links. */
  hrefFor?: (runId: string) => Route;
}

/** A whole percentage as text, or the words for a missing score. */
function percentText(value: number | null): string {
  return value === null ? t("adminEvals.noScore") : t("adminEvals.percent", { percent: value });
}

function RunRow({ run, hrefFor }: { run: EvalRun; hrefFor?: (runId: string) => Route }) {
  return (
    <TableRow data-run={run.id}>
      <TableCell className="whitespace-normal">
        {hrefFor === undefined ? (
          <span className="font-medium text-fg">{run.name}</span>
        ) : (
          <Link
            href={hrefFor(run.id)}
            className="font-medium text-fg underline-offset-4 hover:underline"
          >
            {run.name}
          </Link>
        )}
      </TableCell>
      <TableCell>
        <code className="font-mono text-xs text-fg">{run.model}</code>
      </TableCell>
      <TableCell>
        <StatusChip
          status={run.status}
          tone={runStatusTone(run.status)}
          label={runStatusLabel(run.status)}
        />
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {percentText(scorePercent(run.score))}
      </TableCell>
      <TableCell className="text-fg-muted">{formatDateTime(run.startedAt)}</TableCell>
    </TableRow>
  );
}

/**
 * The evaluation runs: how many there are, their average score and how many passed and failed,
 * then each run, newest first, with its model, outcome, score and start, or an empty state
 * before the first run.
 */
export function AdminEvalsView({ runs, hrefFor }: AdminEvalsViewProps) {
  const summary = evalSummary(runs);
  return (
    <div data-slot="admin-evals" className="flex flex-col gap-6">
      <PageHeader title={t("adminEvals.title")} description={t("adminEvals.intro")} />
      {runs.length === 0 ? (
        <EmptyState title={t("adminEvals.empty.title")} body={t("adminEvals.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminEvals.stat.total")} value={summary.total} tone="info" />
            <StatCard
              label={t("adminEvals.stat.average")}
              value={percentText(summary.averageScore)}
              hint={t("adminEvals.stat.averageHint", { count: summary.scored })}
            />
            <StatCard label={t("adminEvals.stat.passed")} value={summary.passed} tone="success" />
            <StatCard
              label={t("adminEvals.stat.failed")}
              value={summary.failed}
              tone={summary.failed > 0 ? "danger" : "neutral"}
            />
          </div>
          <Table>
            <TableCaption className="sr-only">{t("adminEvals.caption")}</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("adminEvals.column.run")}</TableHead>
                <TableHead scope="col">{t("adminEvals.column.model")}</TableHead>
                <TableHead scope="col">{t("adminEvals.column.status")}</TableHead>
                <TableHead scope="col" className="text-right">
                  {t("adminEvals.column.score")}
                </TableHead>
                <TableHead scope="col">{t("adminEvals.column.started")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortRuns(runs).map((run) => (
                <RunRow key={run.id} run={run} hrefFor={hrefFor} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
