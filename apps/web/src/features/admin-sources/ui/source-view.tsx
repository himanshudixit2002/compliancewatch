import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Banner,
  EmptyState,
  JsonView,
  KeyValue,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type KeyValueItem,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import { DocumentStatusChip, RunsTable } from "@/shared/ui/pipeline";
import { RefreshButton } from "@/shared/ui/refresh-button";
import { ServiceError } from "@/shared/ui/service-error";
import type { SourceFacts } from "../model/source";
import type { SourcePage } from "../queries";
import { FetchPanel } from "./fetch-panel";
import { SettingsPanel } from "./settings-panel";
import type { FetchResult, SettingsResult } from "./source-shared";
import { UploadPanel } from "./upload-panel";
import type { WriteAction } from "@/shared/ui/write-outcome";

export interface SourceViewProps {
  title: string;
  crumbs: readonly Crumb[];
  page: SourcePage;
  /** Bound to the source; null when the session may only read. */
  editAction: WriteAction<SettingsResult> | null;
  fetchAction: WriteAction<FetchResult> | null;
}

function facts(source: SourceFacts): KeyValueItem[] {
  return [
    {
      key: "key",
      label: t("adminSources.facts.key"),
      value: <code className="font-mono text-xs">{source.key}</code>,
      copy: source.key,
    },
    {
      key: "adapter",
      label: t("adminSources.facts.adapter"),
      value: <code className="font-mono text-xs">{source.adapterType}</code>,
    },
    {
      key: "regulator",
      label: t("adminSources.facts.regulator"),
      value: source.regulator ?? t("adminSources.noRegulator"),
    },
    {
      key: "site",
      label: t("adminSources.facts.site"),
      value: source.site ?? t("adminSources.facts.noSite"),
    },
    { key: "type", label: t("adminSources.facts.type"), value: source.docType },
    {
      key: "status",
      label: t("adminSources.facts.status"),
      value: (
        <span className="flex flex-wrap items-center gap-2">
          <StatusChip
            status={source.status.label}
            tone={source.status.tone}
            label={source.status.label}
          />
          <span className="text-fg-muted">{source.switches}</span>
        </span>
      ),
    },
    ...(source.listable
      ? [
          { key: "cadence", label: t("adminSources.facts.cadence"), value: source.cadence },
          {
            key: "freshness",
            label: t("adminSources.facts.freshness"),
            value: (
              <span className="flex flex-wrap items-center gap-2">
                <StatusChip
                  status={source.freshness.label}
                  tone={source.freshness.tone}
                  label={source.freshness.label}
                />
                {source.freshness.detail === null ? null : (
                  <span className="text-fg-muted">{source.freshness.detail}</span>
                )}
              </span>
            ),
          },
          {
            key: "listed",
            label: t("adminSources.facts.lastListed"),
            value:
              source.lastListed === null ? (
                t("adminSources.facts.neverListed")
              ) : (
                <time dateTime={source.lastListed.iso}>{source.lastListed.text}</time>
              ),
          },
          {
            key: "watermark",
            label: t("adminSources.facts.watermark"),
            value: source.watermark ?? t("adminSources.noWatermark"),
          },
        ]
      : []),
    { key: "documents", label: t("adminSources.facts.documents"), value: source.documents },
    ...(source.lastError === ""
      ? []
      : [
          {
            key: "error",
            label: t("adminSources.facts.lastError"),
            value: <span className="text-danger">{source.lastError}</span>,
          },
        ]),
    { key: "created", label: t("adminSources.facts.created"), value: source.created },
    { key: "updated", label: t("adminSources.facts.updated"), value: source.updated },
  ];
}

/**
 * One source: its facts and its adapter type's parameters; for an admin, its settings, "Fetch
 * now" for a source that lists documents, and the upload form for an upload-only one; its stored
 * documents a page at a time, each opening its own page and its stored file; and its latest crawl
 * runs, with the way to all of them.
 */
export function SourceView({ title, crumbs, page, editAction, fetchAction }: SourceViewProps) {
  const source = page.facts;
  const access = page.access;
  return (
    <div
      data-slot="admin-source"
      data-source={source.key}
      className="flex max-w-6xl flex-col gap-8"
    >
      <PageHeader
        title={title}
        description={t("adminSources.source.description", { name: source.name, key: source.key })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <section aria-labelledby="source-facts" className="flex flex-col gap-3">
        <h2 id="source-facts" className="text-lg font-semibold text-fg">
          {t("adminSources.facts.title")}
        </h2>
        {source.listable ? null : (
          <Badge tone="info" className="self-start" data-slot="upload-only">
            {t("adminSources.switches.uploadOnly")}
          </Badge>
        )}
        <KeyValue items={facts(source)} data-slot="source-facts" />
        <JsonView value={source.parameters} label={t("adminSources.facts.parameters")} />
      </section>

      {access.allowed ? null : (
        <Banner tone="neutral" title={access.title} data-slot="source-read-only">
          {access.detail === undefined ? t("adminSources.access.readOnly") : access.detail}
        </Banner>
      )}
      {source.listable && fetchAction !== null ? (
        <FetchPanel
          action={fetchAction}
          flag={{ name: page.crawlFlag.name, variable: page.crawlFlag.variable }}
        />
      ) : null}
      {!source.listable && access.allowed ? (
        <UploadPanel
          href={page.upload.href}
          sourceName={source.name}
          sourceType={source.docType}
          maxBytes={page.upload.maxBytes}
        />
      ) : null}
      {editAction === null ? null : (
        <SettingsPanel action={editAction} defaults={page.settings} listable={source.listable} />
      )}

      <section aria-labelledby="source-documents" className="flex flex-col gap-3">
        <h2 id="source-documents" className="text-lg font-semibold text-fg">
          {t("adminSources.documents.title")}
        </h2>
        {page.documentsError !== null ? (
          <ServiceError error={page.documentsError} />
        ) : page.documents === null ? null : page.documents.rows.length === 0 ? (
          <>
            <EmptyState
              title={
                page.documents.later
                  ? t("adminSources.documents.laterTitle")
                  : t("adminSources.documents.emptyTitle")
              }
              body={
                page.documents.later
                  ? t("adminSources.documents.laterBody")
                  : source.listable
                    ? t("adminSources.documents.emptyBody")
                    : t("adminSources.documents.emptyUploadBody")
              }
            />
            <KeysetPager
              nextHref={null}
              firstHref={page.documents.firstHref}
              label={t("adminSources.documents.pager")}
              nextLabel={t("adminSources.documents.next")}
              firstLabel={t("adminSources.documents.first")}
            />
          </>
        ) : (
          <>
            <Table scrollLabel={t("adminSources.documents.region")}>
              <TableCaption className="text-left text-sm text-fg-muted">
                {t("adminSources.documents.caption", { count: page.documents.rows.length })}
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("adminSources.documents.column.document")}</TableHead>
                  <TableHead>{t("adminSources.documents.column.published")}</TableHead>
                  <TableHead>{t("adminSources.documents.column.status")}</TableHead>
                  <TableHead>{t("adminSources.documents.column.file")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {page.documents.rows.map((row) => (
                  <TableRow
                    key={row.documentId}
                    data-document={row.documentId}
                    data-status={row.status}
                  >
                    <TableCell className="align-top whitespace-normal">
                      <Link
                        href={row.href as Route}
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        {row.title}
                      </Link>
                      {row.externalRef === "" || row.externalRef === row.title ? null : (
                        <span className="block text-xs text-fg-muted">{row.externalRef}</span>
                      )}
                      <span className="block text-xs text-fg-muted">{row.type}</span>
                    </TableCell>
                    <TableCell className="align-top text-sm">
                      {row.published ?? (
                        <span className="text-fg-muted">{t("adminSources.documents.undated")}</span>
                      )}
                      <span className="block text-xs text-fg-muted">
                        {t("adminSources.documents.fetched")}{" "}
                        <time dateTime={row.fetchedIso}>{row.fetched}</time>
                      </span>
                    </TableCell>
                    <TableCell className="align-top">
                      <DocumentStatusChip status={row.status} />
                      {row.parser === null ? null : (
                        <span className="mt-1 block font-mono text-xs text-fg-muted">
                          {row.parser}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="align-top text-sm">
                      <a
                        href={row.rawHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        {t("adminSources.documents.openFile")}
                      </a>
                      <span className="block text-xs text-fg-muted">{row.content}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <KeysetPager
              nextHref={page.documents.nextHref}
              firstHref={page.documents.firstHref}
              label={t("adminSources.documents.pager")}
              nextLabel={t("adminSources.documents.next")}
              firstLabel={t("adminSources.documents.first")}
            />
          </>
        )}
      </section>

      <section aria-labelledby="source-runs" className="flex flex-col gap-3">
        <h2 id="source-runs" className="text-lg font-semibold text-fg">
          {t("adminSources.runs.title")}
        </h2>
        {page.runsError !== null ? (
          <ServiceError error={page.runsError} />
        ) : page.runs === null ? null : (
          <RunsTable
            runs={page.runs}
            caption={t("adminSources.runs.caption", { count: page.runs.length })}
            showSource={false}
            empty={{
              title: t("adminSources.runs.emptyTitle"),
              body: source.listable
                ? t("adminSources.runs.emptyBody")
                : t("adminSources.runs.emptyUploadBody"),
            }}
          />
        )}
        {source.listable ? (
          <Link
            href={page.everyRunHref as Route}
            className="self-start text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("adminSources.runs.every")}
          </Link>
        ) : null}
      </section>
    </div>
  );
}
