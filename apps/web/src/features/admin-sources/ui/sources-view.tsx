import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Banner,
  EmptyState,
  ErrorState,
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
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RefreshButton } from "@/shared/ui/refresh-button";
import { StatCard } from "@/shared/ui/stat-card";
import type { AddSourceNote, CrawlState, SourcesView as SourcesViewModel } from "../model/sources";

export interface SourcesViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: SourcesViewModel;
  /** Shown to an admin: why the page offers no way to add a source yet. */
  addNote: AddSourceNote | null;
}

/**
 * The crawl switch as the web server can know it: the flag as the registry declares it, off by
 * default, held by the pipeline in its own environment (the web server cannot read it), what off
 * means, and the schedule's latest crawl.
 */
export function CrawlBanner({ crawl }: { crawl: CrawlState }) {
  const latest = crawl.latestScheduled;
  return (
    <Banner
      tone="info"
      title={t("adminSources.crawl.title", { flag: crawl.flag.name })}
      data-slot="crawl-banner"
    >
      <p>
        {t(
          crawl.flag.defaultOn ? "adminSources.crawl.defaultOn" : "adminSources.crawl.defaultOff",
          {
            variable: crawl.flag.variable,
          },
        )}
      </p>
      <p>{t("adminSources.crawl.offMeans")}</p>
      <p data-slot="latest-scheduled">
        {latest.kind === "none" ? (
          t("adminSources.crawl.neverScheduled")
        ) : latest.kind === "error" ? (
          t("adminSources.crawl.scheduledUnknown", {
            reason: latest.message,
            id: latest.correlationId ?? t("common.none"),
          })
        ) : (
          <>
            {t("adminSources.crawl.lastScheduled", {
              source: latest.sourceKey ?? t("common.unknown"),
              status: latest.summary.statusLabel,
            })}{" "}
            <time dateTime={latest.summary.startedIso}>{latest.summary.started}</time>
          </>
        )}
      </p>
    </Banner>
  );
}

/**
 * Every source the pipeline reads: its name and key (opening its page), adapter type, regulator
 * and site, the documents it holds, how it stands and whether the schedule may crawl it, its
 * cadence and freshness, its last listing and latest run, its watermark and last error. Above the
 * list, the crawl switch and a count of the sources that need a look.
 */
export function SourcesView({ title, crumbs, view, addNote }: SourcesViewProps) {
  const { rows, counts } = view;
  return (
    <div data-slot="admin-sources" className="flex max-w-7xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("adminSources.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <CrawlBanner crawl={view.crawl} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-slot="source-counts">
        <StatCard label={t("adminSources.stat.total")} value={counts.total} tone="info" />
        <StatCard
          label={t("adminSources.stat.failing")}
          value={counts.failing}
          tone={counts.failing > 0 ? "danger" : "neutral"}
        />
        <StatCard
          label={t("adminSources.stat.behind")}
          value={counts.behind}
          tone={counts.behind > 0 ? "warning" : "neutral"}
        />
        <StatCard label={t("adminSources.stat.uploadOnly")} value={counts.uploadOnly} />
      </div>
      {rows.length === 0 ? (
        <EmptyState title={t("adminSources.empty.title")} body={t("adminSources.empty.body")} />
      ) : (
        <Table scrollLabel={t("adminSources.tableRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("adminSources.caption", { count: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("adminSources.column.source")}</TableHead>
              <TableHead>{t("adminSources.column.adapter")}</TableHead>
              <TableHead>{t("adminSources.column.status")}</TableHead>
              <TableHead>{t("adminSources.column.freshness")}</TableHead>
              <TableHead>{t("adminSources.column.lastCrawl")}</TableHead>
              <TableHead>{t("adminSources.column.watermark")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.key}
                data-source={row.key}
                data-status={row.status}
                data-freshness={row.freshness.state}
              >
                <TableCell className="align-top">
                  <Link
                    href={row.href as Route}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    {row.name}
                  </Link>
                  <code className="block font-mono text-xs text-fg-muted">{row.key}</code>
                  <span className="block text-xs text-fg-muted">
                    {t("adminSources.documentsHeld", { count: row.documents, type: row.docType })}
                  </span>
                </TableCell>
                <TableCell className="align-top">
                  <code className="font-mono text-xs">{row.adapterType}</code>
                  <span className="block text-xs text-fg-muted">
                    {row.regulator ?? t("adminSources.noRegulator")}
                  </span>
                  {row.site === null ? null : (
                    <span className="block text-xs break-all text-fg-muted">{row.site}</span>
                  )}
                </TableCell>
                <TableCell className="align-top">
                  <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
                  <span className="mt-1 block text-xs text-fg-muted">{row.switches}</span>
                  {row.lastError === "" ? null : (
                    <span className="mt-1 block max-w-xs text-xs whitespace-normal text-danger">
                      {t("adminSources.lastError", { error: row.lastError })}
                    </span>
                  )}
                </TableCell>
                <TableCell className="align-top">
                  {row.uploadOnly ? (
                    <span className="text-sm text-fg-muted">
                      {t("adminSources.uploadOnlyFresh")}
                    </span>
                  ) : (
                    <>
                      <StatusChip
                        status={row.freshness.state}
                        tone={row.freshness.tone}
                        label={row.freshness.label}
                      />
                      {row.freshness.detail === null ? null : (
                        <span className="mt-1 block text-xs text-fg-muted">
                          {row.freshness.detail}
                        </span>
                      )}
                      <span className="block text-xs text-fg-muted">{row.cadence}</span>
                    </>
                  )}
                </TableCell>
                <TableCell className="align-top text-sm">
                  {row.latestRun === null ? (
                    <span className="text-fg-muted">{t("adminSources.noRun")}</span>
                  ) : (
                    <span className="flex flex-col gap-1">
                      <time dateTime={row.latestRun.startedIso}>{row.latestRun.started}</time>
                      <span className="flex flex-wrap items-center gap-2">
                        <StatusChip
                          status={row.latestRun.status}
                          tone={row.latestRun.statusTone}
                          label={row.latestRun.statusLabel}
                        />
                        {row.latestRun.backfill ? (
                          <Badge tone="info">{row.latestRun.triggerLabel}</Badge>
                        ) : (
                          <span className="text-xs text-fg-muted">
                            {row.latestRun.triggerLabel}
                          </span>
                        )}
                      </span>
                    </span>
                  )}
                  {row.lastListed === null ? null : (
                    <span className="mt-1 block text-xs text-fg-muted">
                      {t("adminSources.lastListed")}{" "}
                      <time dateTime={row.lastListed.iso}>{row.lastListed.text}</time>
                    </span>
                  )}
                </TableCell>
                <TableCell className="align-top text-sm">
                  {row.watermark ?? (
                    <span className="text-fg-muted">{t("adminSources.noWatermark")}</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {addNote === null ? null : (
        <Banner
          tone="neutral"
          title={t("adminSources.addNote.title", { title: addNote.title })}
          data-slot="add-source-note"
        >
          <p>{addNote.notes}</p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {addNote.routes.map((route) => (
              <li key={route}>
                <code className="font-mono text-xs">{route}</code>
              </li>
            ))}
          </ul>
        </Banner>
      )}
    </div>
  );
}

export interface SourcesErrorProps {
  title: string;
  crumbs: readonly Crumb[];
  error: {
    message: string;
    status?: number;
    requestId: string;
    problem?: { detail?: string | null };
  };
}

/** The list could not be read: the page's h1 and the problem with its correlation id. */
export function SourcesError({ title, crumbs, error }: SourcesErrorProps) {
  return (
    <div data-slot="admin-sources" className="flex max-w-7xl flex-col gap-6">
      <PageHeader title={title} breadcrumbs={<Breadcrumbs crumbs={crumbs} />} />
      <ErrorState
        title={error.message}
        detail={error.problem?.detail ?? undefined}
        status={error.status}
        correlationId={error.requestId === "" ? undefined : error.requestId}
      />
    </div>
  );
}
