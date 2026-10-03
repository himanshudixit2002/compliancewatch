import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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
  VisuallyHidden,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  backfillCounts,
  backfillStatusLabel,
  backfillStatusTone,
  type BackfillJob,
} from "../model/backfill";

/** A server action that starts a full rebuild. */
export type StartBackfillAction = (formData: FormData) => Promise<void>;

export interface AdminBackfillViewProps {
  /** The jobs, newest first. */
  jobs: readonly BackfillJob[];
  /** Offered above the jobs; without it the page cannot start a backfill. */
  startAction?: StartBackfillAction;
}

function JobProgress({ job }: { job: BackfillJob }) {
  if (job.status === "pending") {
    return <span className="text-fg-muted">{t("adminBackfill.progress.waiting")}</span>;
  }
  if (job.total === null) {
    return <span>{t("adminBackfill.progress.uncounted", { processed: job.processed })}</span>;
  }
  return (
    <ProgressBar
      className="min-w-40"
      label={
        <VisuallyHidden>{t("adminBackfill.progress.label", { name: job.name })}</VisuallyHidden>
      }
      value={job.processed}
      max={job.total}
      valueText={t("adminBackfill.progress.counted", {
        processed: job.processed,
        total: job.total,
      })}
    />
  );
}

function StartBackfill({ action }: { action: StartBackfillAction }) {
  return (
    <Card data-slot="start-backfill" className="gap-4">
      <CardHeader>
        <CardTitle>
          <h2 className="text-base font-semibold text-fg">{t("adminBackfill.start.title")}</h2>
        </CardTitle>
        <CardDescription>{t("adminBackfill.start.body")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form action={action}>
          <Button type="submit">{t("adminBackfill.start.submit")}</Button>
        </form>
      </CardContent>
    </Card>
  );
}

function JobsTable({ jobs }: { jobs: readonly BackfillJob[] }) {
  return (
    <Table>
      <TableCaption className="sr-only">{t("adminBackfill.caption")}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("adminBackfill.column.job")}</TableHead>
          <TableHead>{t("adminBackfill.column.status")}</TableHead>
          <TableHead>{t("adminBackfill.column.progress")}</TableHead>
          <TableHead>{t("adminBackfill.column.started")}</TableHead>
          <TableHead>{t("adminBackfill.column.finished")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id} data-job={job.id}>
            <TableCell className="whitespace-normal">
              <span className="block font-medium text-fg">{job.name}</span>
              <span className="block text-xs text-fg-muted">
                {t("adminBackfill.service", { service: job.service })}
              </span>
            </TableCell>
            <TableCell>
              <StatusChip
                status={job.status}
                tone={backfillStatusTone(job.status)}
                label={backfillStatusLabel(job.status)}
              />
            </TableCell>
            <TableCell>
              <JobProgress job={job} />
            </TableCell>
            <TableCell className="text-fg-muted">
              {job.startedAt === null
                ? t("adminBackfill.notStarted")
                : formatDateTime(job.startedAt)}
            </TableCell>
            <TableCell className="text-fg-muted">
              {job.finishedAt === null
                ? t("adminBackfill.notFinished")
                : formatDateTime(job.finishedAt)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The backfill console for admins: the form that starts a full rebuild when the page offers
 * one, how many jobs there are and how many are running, completed or failed, then each job
 * with its progress as the job reports it.
 */
export function AdminBackfillView({ jobs, startAction }: AdminBackfillViewProps) {
  const counts = backfillCounts(jobs);
  return (
    <div data-slot="admin-backfill" className="flex flex-col gap-6">
      <PageHeader title={t("adminBackfill.title")} description={t("adminBackfill.description")} />
      {startAction === undefined ? null : <StartBackfill action={startAction} />}
      {jobs.length === 0 ? (
        <EmptyState title={t("adminBackfill.empty.title")} body={t("adminBackfill.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminBackfill.stat.total")} value={counts.total} tone="info" />
            <StatCard label={t("adminBackfill.stat.running")} value={counts.running} />
            <StatCard
              label={t("adminBackfill.stat.completed")}
              value={counts.completed}
              tone="success"
            />
            <StatCard
              label={t("adminBackfill.stat.failed")}
              value={counts.failed}
              tone={counts.failed > 0 ? "danger" : "neutral"}
            />
          </div>
          <JobsTable jobs={jobs} />
        </>
      )}
    </div>
  );
}
