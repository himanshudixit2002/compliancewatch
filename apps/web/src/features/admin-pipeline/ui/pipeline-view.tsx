import {
  Button,
  EmptyState,
  PageHeader,
  ProgressBar,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  VisuallyHidden,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  PIPELINE_RUN_STATUSES,
  RUN_ID_FIELD,
  formatDuration,
  pipelineCounts,
  runDurationSeconds,
  runStatusLabel,
  runStatusTone,
  type PipelineRun,
} from "../model/pipeline";

/** A server action that re-runs the run named by the form's RUN_ID_FIELD. */
export type RetryAction = (formData: FormData) => Promise<void>;

export interface PipelineViewProps {
  runs: readonly PipelineRun[];
  /** Offered on each failed run; without it no retry is offered. */
  retryAction?: RetryAction;
}

function RunProgress({ run }: { run: PipelineRun }) {
  if (run.status === "pending") {
    return <span className="text-fg-muted">{t("adminPipeline.progress.waiting")}</span>;
  }
  if (run.total === null) {
    return <span>{t("adminPipeline.progress.uncounted", { processed: run.processed })}</span>;
  }
  return (
    <ProgressBar
      className="min-w-40"
      label={
        <VisuallyHidden>{t("adminPipeline.progress.label", { name: run.name })}</VisuallyHidden>
      }
      value={run.processed}
      max={run.total}
      valueText={t("adminPipeline.progress.counted", {
        processed: run.processed,
        total: run.total,
      })}
    />
  );
}

function RunRow({ run, retryAction }: { run: PipelineRun; retryAction?: RetryAction }) {
  const seconds = runDurationSeconds(run);
  return (
    <TableRow data-run={run.id}>
      <TableCell className="whitespace-normal">
        <span className="block font-medium text-fg">{run.name}</span>
        <span className="block text-xs text-fg-muted">{run.stage}</span>
        {run.error === null ? null : (
          <span className="block text-xs text-danger">
            {t("adminPipeline.error", { error: run.error })}
          </span>
        )}
      </TableCell>
      <TableCell>
        <StatusChip
          status={run.status}
          tone={runStatusTone(run.status)}
          label={runStatusLabel(run.status)}
        />
      </TableCell>
      <TableCell>
        <RunProgress run={run} />
      </TableCell>
      <TableCell className="text-fg-muted">
        {run.startedAt === null ? t("adminPipeline.notStarted") : formatDateTime(run.startedAt)}
      </TableCell>
      <TableCell className="text-fg-muted">
        {seconds === null ? t("adminPipeline.notFinished") : formatDuration(seconds)}
      </TableCell>
      {retryAction === undefined ? null : (
        <TableCell>
          {run.status === "failed" ? (
            <form action={retryAction}>
              <input type="hidden" name={RUN_ID_FIELD} value={run.id} />
              <Button type="submit" variant="secondary" size="sm">
                {t("adminPipeline.retry")}
                <VisuallyHidden> {run.name}</VisuallyHidden>
              </Button>
            </form>
          ) : null}
        </TableCell>
      )}
    </TableRow>
  );
}

function RunsTable({ runs, retryAction }: PipelineViewProps) {
  if (runs.length === 0) {
    return (
      <EmptyState title={t("adminPipeline.noMatch.title")} body={t("adminPipeline.noMatch.body")} />
    );
  }
  return (
    <Table>
      <TableCaption className="sr-only">{t("adminPipeline.caption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("adminPipeline.column.run")}</TableHead>
          <TableHead>{t("adminPipeline.column.status")}</TableHead>
          <TableHead>{t("adminPipeline.column.progress")}</TableHead>
          <TableHead>{t("adminPipeline.column.started")}</TableHead>
          <TableHead>{t("adminPipeline.column.duration")}</TableHead>
          {retryAction === undefined ? null : (
            <TableHead>{t("adminPipeline.column.actions")}</TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <RunRow key={run.id} run={run} retryAction={retryAction} />
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The pipeline monitor for the regulatory team: how many runs there are and how many are
 * running, completed or failed, then the runs under status tabs with each one's progress,
 * timing and failure, and a retry on failed runs when the page offers one.
 */
export function PipelineView({ runs, retryAction }: PipelineViewProps) {
  const counts = pipelineCounts(runs);
  const tabs = [
    { value: "all", label: t("adminPipeline.tab.all"), runs },
    ...PIPELINE_RUN_STATUSES.map((status) => ({
      value: status,
      label: runStatusLabel(status),
      runs: runs.filter((run) => run.status === status),
    })),
  ];
  return (
    <div data-slot="admin-pipeline" className="flex flex-col gap-6">
      <PageHeader title={t("adminPipeline.title")} description={t("adminPipeline.description")} />
      {runs.length === 0 ? (
        <EmptyState title={t("adminPipeline.empty.title")} body={t("adminPipeline.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminPipeline.stat.total")} value={counts.total} tone="info" />
            <StatCard label={t("adminPipeline.stat.running")} value={counts.running} />
            <StatCard
              label={t("adminPipeline.stat.completed")}
              value={counts.completed}
              tone="success"
            />
            <StatCard
              label={t("adminPipeline.stat.failed")}
              value={counts.failed}
              tone={counts.failed > 0 ? "danger" : "neutral"}
            />
          </div>
          <Tabs defaultValue="all">
            <TabsList aria-label={t("adminPipeline.tabs")}>
              {tabs.map((tab) => (
                <TabsTrigger key={tab.value} value={tab.value}>
                  {t("adminPipeline.tab.count", { label: tab.label, count: tab.runs.length })}
                </TabsTrigger>
              ))}
            </TabsList>
            {tabs.map((tab) => (
              <TabsContent key={tab.value} value={tab.value} className="pt-2">
                <RunsTable runs={tab.runs} retryAction={retryAction} />
              </TabsContent>
            ))}
          </Tabs>
        </>
      )}
    </div>
  );
}
