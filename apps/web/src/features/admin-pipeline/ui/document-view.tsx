import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Banner,
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
  type KeyValueItem,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { DocumentStatusChip } from "@/shared/ui/pipeline";
import { RefreshButton } from "@/shared/ui/refresh-button";
import type { WriteAction } from "@/shared/ui/write-outcome";
import type { DocumentPageView } from "../model/document";
import type { AccessView, WriteResult } from "./pipeline-shared";
import { RetryPanel } from "./retry-panel";

export interface DocumentViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: DocumentPageView;
  access: AccessView;
  /** Bound to the document; null when the session may only read. */
  retryAction: WriteAction<WriteResult> | null;
  retryKey: string;
}

function recordFacts(view: DocumentPageView): KeyValueItem[] {
  return [
    {
      key: "id",
      label: t("pipelineDocument.facts.id"),
      value: <code className="font-mono text-xs">{view.documentId}</code>,
      copy: view.documentId,
    },
    {
      key: "source",
      label: t("pipelineDocument.facts.source"),
      value: (
        <Link
          href={view.sourceHref as Route}
          className="font-mono text-primary underline-offset-2 hover:underline"
        >
          {view.sourceKey}
        </Link>
      ),
    },
    {
      key: "listed",
      label: t("pipelineDocument.facts.listedAt"),
      value: <code className="font-mono text-xs break-all">{view.sourceUrl}</code>,
      copy: view.sourceUrl,
    },
    {
      key: "ref",
      label: t("pipelineDocument.facts.ref"),
      value: view.externalRef === "" ? t("common.none") : view.externalRef,
    },
    {
      key: "published",
      label: t("pipelineDocument.facts.published"),
      value: view.published ?? t("pipelineDocument.facts.undated"),
    },
    {
      key: "fetched",
      label: t("pipelineDocument.facts.fetched"),
      value: <time dateTime={view.fetchedIso}>{view.fetched}</time>,
    },
    {
      key: "status",
      label: t("pipelineDocument.facts.status"),
      value: <DocumentStatusChip status={view.status} />,
    },
    { key: "readAs", label: t("pipelineDocument.facts.readAs"), value: view.readAs },
    {
      key: "uploader",
      label: t("pipelineDocument.facts.uploaderType"),
      value: view.uploaderType ?? t("pipelineDocument.facts.sourceType"),
    },
    {
      key: "file",
      label: t("pipelineDocument.facts.file"),
      value: (
        <span className="flex flex-col gap-0.5">
          <span>
            {t("pipelineDocument.facts.fileLine", { type: view.contentType, size: view.size })}
          </span>
          <a
            href={view.rawHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("pipelineDocument.facts.openFile")}
          </a>
        </span>
      ),
    },
    {
      key: "sha256",
      label: t("pipelineDocument.facts.sha256"),
      value: <code className="font-mono text-xs break-all">{view.sha256}</code>,
      copy: view.sha256,
    },
    {
      key: "parser",
      label: t("pipelineDocument.facts.parser"),
      value: view.parser ?? t("pipelineDocument.facts.notParsed"),
    },
  ];
}

/**
 * One stored document for the regulatory team: the record (where it was listed or uploaded, when
 * it was first fetched, its digest and its stored file, its last parse), how the pipeline reads it
 * (its type, its classification with who decided it and why, its rule extraction by the current
 * prompt), the retries people asked for, newest first, and for an admin the retry.
 */
export function DocumentView({
  title,
  crumbs,
  view,
  access,
  retryAction,
  retryKey,
}: DocumentViewProps) {
  const classification = view.classification;
  const extraction = view.extraction;
  return (
    <div
      data-slot="pipeline-document"
      data-document={view.documentId}
      className="flex max-w-6xl flex-col gap-8"
    >
      <PageHeader
        title={title}
        description={t("pipelineDocument.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <section aria-labelledby="document-record" className="flex flex-col gap-3">
        <h2 id="document-record" className="text-lg font-semibold text-fg">
          {t("pipelineDocument.record")}
        </h2>
        <KeyValue items={recordFacts(view)} data-slot="document-facts" />
      </section>

      <section aria-labelledby="document-classification" className="flex flex-col gap-3">
        <h2 id="document-classification" className="text-lg font-semibold text-fg">
          {t("pipelineDocument.classification.title")}
        </h2>
        {classification === null ? (
          <p className="text-sm text-fg-muted" data-slot="no-classification">
            {t("pipelineDocument.classification.none")}
          </p>
        ) : (
          <>
            <KeyValue
              data-slot="classification-facts"
              items={[
                {
                  key: "by",
                  label: t("pipelineDocument.classification.by"),
                  value: classification.by,
                },
                ...(classification.decidedBy === null
                  ? []
                  : [
                      {
                        key: "decidedBy",
                        label: t("pipelineDocument.classification.decidedBy"),
                        value: (
                          <code className="font-mono text-xs">{classification.decidedBy}</code>
                        ),
                      },
                    ]),
                {
                  key: "type",
                  label: t("pipelineDocument.classification.type"),
                  value: classification.type,
                },
                {
                  key: "relevance",
                  label: t("pipelineDocument.classification.relevance"),
                  value: classification.relevance,
                },
                {
                  key: "confidence",
                  label: t("pipelineDocument.classification.confidence"),
                  value: classification.confidence,
                },
                {
                  key: "route",
                  label: t("pipelineDocument.classification.route"),
                  value: classification.route,
                },
                {
                  key: "at",
                  label: t("pipelineDocument.classification.at"),
                  value: <time dateTime={classification.atIso}>{classification.at}</time>,
                },
                ...(classification.taskId === null
                  ? []
                  : [
                      {
                        key: "task",
                        label: t("pipelineDocument.classification.task"),
                        value: <code className="font-mono text-xs">{classification.taskId}</code>,
                      },
                    ]),
              ]}
            />
            {classification.reasons.length === 0 ? null : (
              <div className="flex flex-col gap-1">
                <p className="text-sm font-medium text-fg">
                  {t("pipelineDocument.classification.reasons")}
                </p>
                <ul className="list-disc pl-5 text-sm">
                  {classification.reasons.map((reason, index) => (
                    <li key={index}>{reason}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="document-extraction" className="flex flex-col gap-3">
        <h2 id="document-extraction" className="text-lg font-semibold text-fg">
          {t("pipelineDocument.extraction.title")}
        </h2>
        {extraction === null ? (
          <p className="text-sm text-fg-muted" data-slot="no-extraction">
            {t("pipelineDocument.extraction.none")}
          </p>
        ) : (
          <KeyValue
            data-slot="extraction-facts"
            items={[
              {
                key: "outcome",
                label: t("pipelineDocument.extraction.outcome"),
                value: (
                  <span className="flex flex-wrap items-center gap-2">
                    {extraction.outcome}
                    {extraction.needsReview ? (
                      <Badge tone="warning">{t("adminPipeline.extraction.needsReview")}</Badge>
                    ) : null}
                  </span>
                ),
              },
              {
                key: "model",
                label: t("pipelineDocument.extraction.model"),
                value: <code className="font-mono text-xs">{extraction.model}</code>,
              },
              {
                key: "prompt",
                label: t("pipelineDocument.extraction.prompt"),
                value: extraction.promptVersion,
              },
              {
                key: "issues",
                label: t("pipelineDocument.extraction.issues"),
                value: extraction.issues,
              },
              {
                key: "candidate",
                label: t("pipelineDocument.extraction.candidate"),
                value: <code className="font-mono text-xs">{extraction.candidateId}</code>,
                copy: extraction.candidateId,
              },
              {
                key: "at",
                label: t("pipelineDocument.extraction.at"),
                value: <time dateTime={extraction.atIso}>{extraction.at}</time>,
              },
            ]}
          />
        )}
      </section>

      <section aria-labelledby="document-retries" className="flex flex-col gap-3">
        <h2 id="document-retries" className="text-lg font-semibold text-fg">
          {t("pipelineDocument.retries.title")}
        </h2>
        {view.retries.length === 0 ? (
          <EmptyState
            heading="h3"
            title={t("pipelineDocument.retries.emptyTitle")}
            body={t("pipelineDocument.retries.emptyBody")}
          />
        ) : (
          <Table scrollLabel={t("pipelineDocument.retries.region")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("pipelineDocument.retries.caption", { count: view.retries.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("pipelineDocument.retries.column.attempt")}</TableHead>
                <TableHead>{t("pipelineDocument.retries.column.stage")}</TableHead>
                <TableHead>{t("pipelineDocument.retries.column.reason")}</TableHead>
                <TableHead>{t("pipelineDocument.retries.column.who")}</TableHead>
                <TableHead>{t("pipelineDocument.retries.column.workflow")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.retries.map((retry) => (
                <TableRow key={retry.attempt} data-attempt={retry.attempt}>
                  <TableCell className="align-top">{retry.attempt}</TableCell>
                  <TableCell className="align-top">
                    {retry.stage}
                    {retry.docType === null ? null : (
                      <span className="block text-xs text-fg-muted">
                        {t("pipelineDocument.retries.asType", { type: retry.docType })}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-md align-top whitespace-normal">
                    {retry.reason}
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    {retry.requestedBy === null ? (
                      t("common.unknown")
                    ) : (
                      <code className="font-mono text-xs">{retry.requestedBy}</code>
                    )}
                    <span className="block text-xs text-fg-muted">
                      <time dateTime={retry.atIso}>{retry.at}</time>
                    </span>
                  </TableCell>
                  <TableCell className="align-top">
                    <code className="font-mono text-xs break-all">{retry.workflowId}</code>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {retryAction !== null && access.allowed ? (
        <RetryPanel action={retryAction} idempotencyKey={retryKey} documentTitle={view.title} />
      ) : (
        <Banner
          tone="neutral"
          title={access.allowed ? t("adminPipeline.access.adminOnly") : access.title}
          data-slot="document-read-only"
        >
          {access.allowed
            ? t("pipelineDocument.retry.readOnly")
            : (access.detail ?? t("pipelineDocument.retry.readOnly"))}
        </Banner>
      )}
    </div>
  );
}
