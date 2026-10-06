import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  DateField,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import {
  CRAWL_STATUSES,
  CRAWL_TRIGGERS,
  DOCUMENT_STATUSES,
  DOCUMENT_TYPES,
} from "@/entities/pipeline/types";
import type { Crumb } from "@/shared/config/nav";
import { t, type MessageKey } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { FilterChips } from "@/shared/ui/filter-chips";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import {
  DocumentStatusChip,
  RunsTable,
  documentStatusLabel,
  documentTypeLabel,
  runStatusLabel,
  runTriggerLabel,
} from "@/shared/ui/pipeline";
import { RefreshButton } from "@/shared/ui/refresh-button";
import { ServiceError } from "@/shared/ui/service-error";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  PIPELINE_PARAMS,
  isFiltered,
  viewChips,
  type DocumentFilter,
  type DocumentRow,
  type OutboxFilter,
  type PagedRows,
  type RunFilter,
} from "../model/operations";
import type { PipelinePage } from "../queries";
import { OutboxTable } from "./outbox-table";
import type { WriteResult } from "./pipeline-shared";

export interface PipelineViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The page itself, without a query: the filter forms' action. */
  pageHref: string;
  page: PipelinePage;
  /** The requeue, for an admin; null when the session may only read. */
  requeueAction: WriteAction<WriteResult> | null;
}

const VIEW_INTROS: Readonly<Record<"runs" | "documents" | "outbox", MessageKey>> = {
  runs: "adminPipeline.viewIntro.runs",
  documents: "adminPipeline.viewIntro.documents",
  outbox: "adminPipeline.viewIntro.outbox",
};

function SourceSelect({
  id,
  value,
  invalid,
  keys,
}: {
  id: string;
  value: string | null;
  invalid: string | undefined;
  keys: readonly string[] | null;
}) {
  const options = [
    { value: "", label: t("adminPipeline.filter.everySource") },
    ...(keys ?? []).map((key) => ({ value: key, label: key })),
  ];
  if (value !== null && keys !== null && !keys.includes(value))
    options.push({ value, label: value });
  return (
    <Field
      id={id}
      label={t("adminPipeline.filter.source")}
      error={invalid === undefined ? undefined : t("adminPipeline.filter.sourceInvalid")}
      description={keys === null ? t("adminPipeline.filter.sourcesUnread") : undefined}
      className="w-56"
    >
      <Select
        name={PIPELINE_PARAMS.source}
        defaultValue={invalid ?? value ?? ""}
        options={options}
      />
    </Field>
  );
}

function RunsFilters({
  pageHref,
  filter,
  keys,
  invalid,
}: {
  pageHref: string;
  filter: RunFilter;
  keys: readonly string[] | null;
  invalid: Readonly<Record<string, string>>;
}) {
  return (
    <form
      method="get"
      action={pageHref}
      aria-label={t("adminPipeline.filter.runsLabel")}
      data-slot="runs-filter"
      className="flex flex-wrap items-end gap-3"
    >
      <SourceSelect
        id="runs-source"
        value={filter.source}
        invalid={invalid[PIPELINE_PARAMS.source]}
        keys={keys}
      />
      <Field id="runs-status" label={t("adminPipeline.filter.status")} className="w-48">
        <Select
          name={PIPELINE_PARAMS.status}
          defaultValue={filter.status ?? ""}
          options={[
            { value: "", label: t("adminPipeline.filter.everyStatus") },
            ...CRAWL_STATUSES.map((status) => ({ value: status, label: runStatusLabel(status) })),
          ]}
        />
      </Field>
      <Field id="runs-trigger" label={t("adminPipeline.filter.trigger")} className="w-56">
        <Select
          name={PIPELINE_PARAMS.trigger}
          defaultValue={filter.trigger ?? ""}
          options={[
            { value: "", label: t("adminPipeline.filter.everyTrigger") },
            ...CRAWL_TRIGGERS.map((trigger) => ({
              value: trigger,
              label: runTriggerLabel(trigger),
            })),
          ]}
        />
      </Field>
      <Button type="submit" variant="secondary">
        {t("adminPipeline.filter.submit")}
      </Button>
    </form>
  );
}

function DocumentsFilters({
  pageHref,
  filter,
  keys,
  invalid,
}: {
  pageHref: string;
  filter: DocumentFilter;
  keys: readonly string[] | null;
  invalid: Readonly<Record<string, string>>;
}) {
  return (
    <form
      method="get"
      action={pageHref}
      aria-label={t("adminPipeline.filter.documentsLabel")}
      data-slot="documents-filter"
      noValidate
      className="flex flex-wrap items-end gap-3"
    >
      <input type="hidden" name={PIPELINE_PARAMS.view} value="documents" />
      <Field id="documents-status" label={t("adminPipeline.filter.status")} className="w-56">
        <Select
          name={PIPELINE_PARAMS.status}
          defaultValue={filter.status ?? ""}
          options={[
            { value: "", label: t("adminPipeline.filter.everyStatus") },
            ...DOCUMENT_STATUSES.map((status) => ({
              value: status,
              label: documentStatusLabel(status),
            })),
          ]}
        />
      </Field>
      <SourceSelect
        id="documents-source"
        value={filter.source}
        invalid={invalid[PIPELINE_PARAMS.source]}
        keys={keys}
      />
      <Field id="documents-type" label={t("adminPipeline.filter.type")} className="w-48">
        <Select
          name={PIPELINE_PARAMS.type}
          defaultValue={filter.type ?? ""}
          options={[
            { value: "", label: t("adminPipeline.filter.everyType") },
            ...DOCUMENT_TYPES.map((type) => ({ value: type, label: documentTypeLabel(type) })),
          ]}
        />
      </Field>
      <DateField
        id="documents-from"
        name={PIPELINE_PARAMS.from}
        label={t("adminPipeline.filter.from")}
        defaultValue={invalid[PIPELINE_PARAMS.from] ?? filter.from ?? ""}
        error={
          invalid[PIPELINE_PARAMS.from] === undefined
            ? undefined
            : t("adminPipeline.filter.dateInvalid")
        }
        className="w-44"
      />
      <DateField
        id="documents-to"
        name={PIPELINE_PARAMS.to}
        label={t("adminPipeline.filter.to")}
        defaultValue={invalid[PIPELINE_PARAMS.to] ?? filter.to ?? ""}
        error={
          invalid[PIPELINE_PARAMS.to] === undefined
            ? undefined
            : t("adminPipeline.filter.toInvalid")
        }
        className="w-44"
      />
      <Button type="submit" variant="secondary">
        {t("adminPipeline.filter.submit")}
      </Button>
      <p className="w-full text-xs text-fg-muted">{t("adminPipeline.filter.datesHelp")}</p>
    </form>
  );
}

function OutboxFilters({
  pageHref,
  filter,
  invalid,
}: {
  pageHref: string;
  filter: OutboxFilter;
  invalid: Readonly<Record<string, string>>;
}) {
  return (
    <form
      method="get"
      action={pageHref}
      aria-label={t("adminPipeline.filter.outboxLabel")}
      data-slot="outbox-filter"
      noValidate
      className="flex flex-wrap items-end gap-3"
    >
      <input type="hidden" name={PIPELINE_PARAMS.view} value="outbox" />
      <Field
        id="outbox-topic"
        label={t("adminPipeline.filter.topic")}
        description={t("adminPipeline.filter.topicHelp")}
        error={
          invalid[PIPELINE_PARAMS.topic] === undefined
            ? undefined
            : t("adminPipeline.filter.topicInvalid")
        }
        className="w-full max-w-sm"
      >
        <Input
          name={PIPELINE_PARAMS.topic}
          defaultValue={invalid[PIPELINE_PARAMS.topic] ?? filter.topic ?? ""}
          autoComplete="off"
          spellCheck={false}
        />
      </Field>
      <Button type="submit" variant="secondary">
        {t("adminPipeline.filter.submit")}
      </Button>
    </form>
  );
}

function DocumentsTable({ rows }: { rows: readonly DocumentRow[] }) {
  return (
    <Table scrollLabel={t("adminPipeline.documents.region")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("adminPipeline.documents.caption", { count: rows.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("adminPipeline.documents.column.document")}</TableHead>
          <TableHead>{t("adminPipeline.documents.column.readAs")}</TableHead>
          <TableHead>{t("adminPipeline.documents.column.classification")}</TableHead>
          <TableHead>{t("adminPipeline.documents.column.extraction")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.documentId} data-document={row.documentId} data-status={row.status}>
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
              <span className="block text-xs text-fg-muted">
                {t("adminPipeline.documents.from")}{" "}
                <Link
                  href={row.sourceHref as Route}
                  className="font-mono text-primary underline-offset-2 hover:underline"
                >
                  {row.sourceKey}
                </Link>
              </span>
              <span className="block text-xs text-fg-muted">
                {row.published === null
                  ? t("adminPipeline.documents.undated")
                  : t("adminPipeline.documents.published", { date: row.published })}
                {"; "}
                {t("adminPipeline.documents.fetched")}{" "}
                <time dateTime={row.fetchedIso}>{row.fetched}</time>
              </span>
            </TableCell>
            <TableCell className="align-top">
              <span className="block text-sm">{row.readAs}</span>
              <span className="mt-1 block">
                <DocumentStatusChip status={row.status} />
              </span>
            </TableCell>
            <TableCell className="align-top text-sm whitespace-normal">
              {row.classification === null ? (
                <span className="text-fg-muted">{t("adminPipeline.documents.notClassified")}</span>
              ) : (
                <span className="flex flex-col gap-0.5" data-slot="classification">
                  <span className="font-medium">{row.classification.by}</span>
                  {row.classification.decidedBy === null ? null : (
                    <span className="text-xs text-fg-muted">
                      {t("adminPipeline.documents.decidedBy")}{" "}
                      <code className="font-mono">{row.classification.decidedBy}</code>
                    </span>
                  )}
                  <span className="text-xs text-fg-muted">
                    {t("adminPipeline.documents.classificationLine", {
                      relevance: row.classification.relevance,
                      confidence: row.classification.confidence,
                    })}
                  </span>
                  <span className="text-xs text-fg-muted">{row.classification.route}</span>
                </span>
              )}
            </TableCell>
            <TableCell className="align-top text-sm whitespace-normal">
              {row.extraction === null ? (
                <span className="text-fg-muted">{t("adminPipeline.documents.notExtracted")}</span>
              ) : (
                <span className="flex flex-col gap-0.5" data-slot="extraction">
                  <span className="font-medium">{row.extraction.outcome}</span>
                  <span className="text-xs text-fg-muted">
                    <code className="font-mono">{row.extraction.model}</code>,{" "}
                    {row.extraction.promptVersion}
                  </span>
                  <span className="text-xs text-fg-muted">{row.extraction.issues}</span>
                  {row.extraction.needsReview ? (
                    <Badge tone="warning" className="self-start">
                      {t("adminPipeline.extraction.needsReview")}
                    </Badge>
                  ) : null}
                </span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function emptyText(
  view: "runs" | "documents" | "outbox",
  later: boolean,
  filtered: boolean,
): { title: string; body: string } {
  if (later)
    return { title: t("adminPipeline.empty.laterTitle"), body: t("adminPipeline.empty.laterBody") };
  if (view === "runs") {
    return filtered
      ? {
          title: t("adminPipeline.empty.runsFilteredTitle"),
          body: t("adminPipeline.empty.filteredBody"),
        }
      : { title: t("adminPipeline.empty.runsTitle"), body: t("adminPipeline.empty.runsBody") };
  }
  if (view === "documents") {
    return filtered
      ? {
          title: t("adminPipeline.empty.documentsFilteredTitle"),
          body: t("adminPipeline.empty.filteredBody"),
        }
      : {
          title: t("adminPipeline.empty.documentsTitle"),
          body: t("adminPipeline.empty.documentsBody"),
        };
  }
  return filtered
    ? {
        title: t("adminPipeline.empty.outboxFilteredTitle"),
        body: t("adminPipeline.empty.filteredBody"),
      }
    : { title: t("adminPipeline.empty.outboxTitle"), body: t("adminPipeline.empty.outboxBody") };
}

function Pager({ list }: { list: PagedRows<unknown> }) {
  return (
    <KeysetPager
      nextHref={list.nextHref}
      firstHref={list.firstHref}
      label={t("adminPipeline.pager")}
      nextLabel={t("adminPipeline.nextPage")}
      firstLabel={t("adminPipeline.firstPage")}
    />
  );
}

/**
 * The pipeline's operations for the regulatory team, one view at a time: every source's crawl
 * runs (a backfill marked as one), every source's documents with how the pipeline reads each one
 * (its type, its classification by the detector or a person, its rule extraction), and the outbox
 * rows the relay gave up on, which an admin requeues once the cause is fixed. Each view filters
 * with a GET form and pages by the pipeline's cursor.
 */
export function PipelineView({ title, crumbs, pageHref, page, requeueAction }: PipelineViewProps) {
  const { read, list, listError, sourceKeys, access } = page;
  const current = read.current;
  const filtered = isFiltered(current);
  return (
    <div
      data-slot="admin-pipeline"
      data-view={current.view}
      className="flex max-w-7xl flex-col gap-6"
    >
      <PageHeader
        title={title}
        description={t("adminPipeline.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <FilterChips label={t("adminPipeline.viewsLabel")} chips={viewChips(current.view)} />
      <p className="max-w-prose text-sm text-fg-muted">{t(VIEW_INTROS[current.view])}</p>
      {current.view === "runs" ? (
        <RunsFilters
          pageHref={pageHref}
          filter={current.filter}
          keys={sourceKeys}
          invalid={read.invalid}
        />
      ) : current.view === "documents" ? (
        <DocumentsFilters
          pageHref={pageHref}
          filter={current.filter}
          keys={sourceKeys}
          invalid={read.invalid}
        />
      ) : (
        <OutboxFilters pageHref={pageHref} filter={current.filter} invalid={read.invalid} />
      )}
      {current.view === "outbox" && !access.allowed ? (
        <Banner tone="neutral" title={access.title} data-slot="pipeline-read-only">
          {access.detail ?? t("adminPipeline.access.readOnly")}
        </Banner>
      ) : null}
      {listError !== null ? <ServiceError error={listError} /> : null}
      {list === null ? null : list.list.rows.length === 0 ? (
        <>
          <EmptyState {...emptyText(list.view, list.list.later, filtered)} />
          <Pager list={list.list} />
        </>
      ) : list.view === "runs" ? (
        <>
          <RunsTable
            runs={list.list.rows}
            caption={t("adminPipeline.runs.caption", { count: list.list.rows.length })}
            showSource
            empty={emptyText("runs", false, filtered)}
          />
          <Pager list={list.list} />
        </>
      ) : list.view === "documents" ? (
        <>
          <DocumentsTable rows={list.list.rows} />
          <Pager list={list.list} />
        </>
      ) : (
        <>
          <OutboxTable rows={list.list.rows} action={access.allowed ? requeueAction : null} />
          <Pager list={list.list} />
        </>
      )}
    </div>
  );
}
