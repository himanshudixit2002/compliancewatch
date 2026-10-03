import type { Route } from "next";
import Link from "next/link";
import {
  Button,
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
  SOURCE_KEY_FIELD,
  canFetch,
  documentTypeLabel,
  formatCount,
  sourceCounts,
  sourceStatusLabel,
  sourceStatusTone,
  type PipelineSource,
} from "../model/sources";

export interface AdminSourcesViewProps {
  sources: readonly PipelineSource[];
  /** A source's history page; without it the source names are not links. */
  hrefFor?: (key: string) => Route;
  /**
   * Asks the pipeline to fetch one source now: a plain form action that receives the source's
   * key in SOURCE_KEY_FIELD. Without it the table has no fetch control.
   */
  fetchAction?: (formData: FormData) => Promise<void>;
}

type SourceRowProps = Omit<AdminSourcesViewProps, "sources"> & { source: PipelineSource };

function SourceRow({ source, hrefFor, fetchAction }: SourceRowProps) {
  return (
    <TableRow data-source={source.key}>
      <TableCell className="whitespace-normal">
        {hrefFor === undefined ? (
          <span className="font-medium text-fg">{source.name}</span>
        ) : (
          <Link
            href={hrefFor(source.key)}
            className="font-medium text-fg underline-offset-4 hover:underline"
          >
            {source.name}
          </Link>
        )}
        <p className="text-xs text-fg-muted">{source.site}</p>
      </TableCell>
      <TableCell>{documentTypeLabel(source.documentType)}</TableCell>
      <TableCell>
        <StatusChip
          status={source.status}
          tone={sourceStatusTone(source.status)}
          label={sourceStatusLabel(source.status)}
        />
      </TableCell>
      <TableCell className="text-fg-muted">
        {source.lastFetchedAt === null
          ? t("adminSources.neverFetched")
          : formatDateTime(source.lastFetchedAt)}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatCount(source.documentCount)}</TableCell>
      {fetchAction === undefined ? null : (
        <TableCell>
          {canFetch(source) ? (
            <form action={fetchAction}>
              <input type="hidden" name={SOURCE_KEY_FIELD} value={source.key} />
              <Button type="submit" variant="secondary" size="sm">
                {t("adminSources.fetchNow")}
                <span className="sr-only"> {source.name}</span>
              </Button>
            </form>
          ) : null}
        </TableCell>
      )}
    </TableRow>
  );
}

/**
 * The sources the pipeline fetches documents from: how many there are, healthy and failing, then
 * each source's document type, state, last fetch and documents collected, with a fetch control
 * when the page supplies the action, or an empty state before any source is configured.
 */
export function AdminSourcesView({ sources, hrefFor, fetchAction }: AdminSourcesViewProps) {
  const counts = sourceCounts(sources);
  return (
    <div data-slot="admin-sources" className="flex flex-col gap-6">
      <PageHeader title={t("adminSources.title")} description={t("adminSources.intro")} />
      {sources.length === 0 ? (
        <EmptyState title={t("adminSources.empty.title")} body={t("adminSources.empty.body")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label={t("adminSources.stat.total")} value={counts.total} tone="info" />
            <StatCard
              label={t("adminSources.stat.healthy")}
              value={counts.healthy}
              tone="success"
            />
            <StatCard
              label={t("adminSources.stat.failing")}
              value={counts.failing}
              tone={counts.failing > 0 ? "danger" : "neutral"}
            />
          </div>
          <Table>
            <TableCaption className="sr-only">{t("adminSources.caption")}</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("adminSources.column.source")}</TableHead>
                <TableHead scope="col">{t("adminSources.column.type")}</TableHead>
                <TableHead scope="col">{t("adminSources.column.status")}</TableHead>
                <TableHead scope="col">{t("adminSources.column.lastFetched")}</TableHead>
                <TableHead scope="col" className="text-right">
                  {t("adminSources.column.documents")}
                </TableHead>
                {fetchAction === undefined ? null : (
                  <TableHead scope="col">{t("adminSources.column.fetch")}</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((source) => (
                <SourceRow
                  key={source.key}
                  source={source}
                  hrefFor={hrefFor}
                  fetchAction={fetchAction}
                />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
