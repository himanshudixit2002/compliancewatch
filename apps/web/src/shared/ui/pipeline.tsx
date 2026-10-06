import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  EmptyState,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";

/**
 * The pipeline's words, shared by the source pages and the pipeline's own: a stored document's
 * status and type, a crawl run's status and trigger (a backfill said as one), and the table of
 * runs both show. The values are the pipeline's (`DocumentStatus`, `DocumentType`, `CrawlStatus`,
 * `CrawlTrigger`); the types are spelled out here because shared code reads no entity, and a value
 * a later spec adds reads humanised rather than missing.
 */
export type PipelineDocumentStatus =
  | "discovered"
  | "parsed"
  | "failed"
  | "irrelevant"
  | "classified"
  | "triage"
  | "reference"
  | "extracted";

export type PipelineDocumentType =
  "notification" | "circular" | "press_release" | "act_amendment" | "statute";

export type PipelineRunStatus = "running" | "completed" | "failed";

export type PipelineRunTrigger = "schedule" | "manual" | "backfill";

export const DOCUMENT_STATUS_LABELS: Readonly<Record<PipelineDocumentStatus, MessageKey>> = {
  discovered: "pipeline.documentStatus.discovered",
  parsed: "pipeline.documentStatus.parsed",
  failed: "pipeline.documentStatus.failed",
  irrelevant: "pipeline.documentStatus.irrelevant",
  classified: "pipeline.documentStatus.classified",
  triage: "pipeline.documentStatus.triage",
  reference: "pipeline.documentStatus.reference",
  extracted: "pipeline.documentStatus.extracted",
};

const DOCUMENT_STATUS_TONES: Readonly<Record<PipelineDocumentStatus, Tone>> = {
  discovered: "neutral",
  parsed: "info",
  failed: "danger",
  irrelevant: "neutral",
  classified: "info",
  triage: "warning",
  reference: "success",
  extracted: "success",
};

export const DOCUMENT_TYPE_LABELS: Readonly<Record<PipelineDocumentType, MessageKey>> = {
  notification: "pipeline.documentType.notification",
  circular: "pipeline.documentType.circular",
  press_release: "pipeline.documentType.pressRelease",
  act_amendment: "pipeline.documentType.actAmendment",
  statute: "pipeline.documentType.statute",
};

export const RUN_STATUS_LABELS: Readonly<Record<PipelineRunStatus, MessageKey>> = {
  running: "pipeline.runStatus.running",
  completed: "pipeline.runStatus.completed",
  failed: "pipeline.runStatus.failed",
};

const RUN_STATUS_TONES: Readonly<Record<PipelineRunStatus, Tone>> = {
  running: "info",
  completed: "success",
  failed: "danger",
};

export const RUN_TRIGGER_LABELS: Readonly<Record<PipelineRunTrigger, MessageKey>> = {
  schedule: "pipeline.trigger.schedule",
  manual: "pipeline.trigger.manual",
  backfill: "pipeline.trigger.backfill",
};

function known<K extends string>(record: Readonly<Record<K, unknown>>, value: string): value is K {
  return Object.hasOwn(record, value);
}

export function documentStatusLabel(status: string): string {
  return known(DOCUMENT_STATUS_LABELS, status)
    ? t(DOCUMENT_STATUS_LABELS[status])
    : humanise(status);
}

export function documentStatusTone(status: string): Tone {
  return known(DOCUMENT_STATUS_TONES, status) ? DOCUMENT_STATUS_TONES[status] : "neutral";
}

/** A document type in words; null (a source the code cannot read) says it is not known. */
export function documentTypeLabel(type: string | null): string {
  if (type === null) return t("pipeline.documentType.unknown");
  return known(DOCUMENT_TYPE_LABELS, type) ? t(DOCUMENT_TYPE_LABELS[type]) : humanise(type);
}

export function runStatusLabel(status: string): string {
  return known(RUN_STATUS_LABELS, status) ? t(RUN_STATUS_LABELS[status]) : humanise(status);
}

export function runStatusTone(status: string): Tone {
  return known(RUN_STATUS_TONES, status) ? RUN_STATUS_TONES[status] : "neutral";
}

/** Why a run ran; a run recorded before the pipeline kept it has no trigger. */
export function runTriggerLabel(trigger: string | null): string {
  if (trigger === null) return t("pipeline.trigger.unknown");
  return known(RUN_TRIGGER_LABELS, trigger) ? t(RUN_TRIGGER_LABELS[trigger]) : humanise(trigger);
}

export interface DocumentStatusChipProps {
  status: string;
}

export function DocumentStatusChip({ status }: DocumentStatusChipProps) {
  return (
    <StatusChip
      status={status}
      tone={documentStatusTone(status)}
      label={documentStatusLabel(status)}
    />
  );
}

/** A crawl run as the table reads it: the pipeline's run, by structure. */
export interface PipelineRunLike {
  runId: string;
  sourceKey: string | null;
  status: string;
  trigger: string | null;
  workflowId: string | null;
  startedAt: string;
  finishedAt: string | null;
  listed: number;
  stored: number;
  duplicates: number;
  failed: number;
  error: string;
}

/** The source's page, where a run's source opens. */
export function sourceHref(key: string): string {
  return hrefFor(screenById("admin.source"), { key });
}

export interface RunsTableProps {
  runs: readonly PipelineRunLike[];
  /** The table's caption: which runs it lists. */
  caption: string;
  /** Show each run's source (the pipeline's list); a source's own page leaves it out. */
  showSource: boolean;
  /** What an empty list says, and why. */
  empty: { title: string; body: string };
}

/**
 * Crawl runs, the latest started first as the pipeline lists them: when each started and ended,
 * why it ran (a backfill is marked as one: it lists part of history and leaves the source's
 * watermark as it was), how it ended, what its listing found (listed; stored, duplicates and
 * failed of the new documents), its workflow on Temporal and its error.
 */
export function RunsTable({ runs, caption, showSource, empty }: RunsTableProps) {
  if (runs.length === 0) return <EmptyState title={empty.title} body={empty.body} />;
  return (
    <Table scrollLabel={t("pipeline.runs.region")}>
      <TableCaption className="text-left text-sm text-fg-muted">{caption}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("pipeline.runs.column.started")}</TableHead>
          {showSource ? <TableHead>{t("pipeline.runs.column.source")}</TableHead> : null}
          <TableHead>{t("pipeline.runs.column.trigger")}</TableHead>
          <TableHead>{t("pipeline.runs.column.status")}</TableHead>
          <TableHead>{t("pipeline.runs.column.found")}</TableHead>
          <TableHead>{t("pipeline.runs.column.workflow")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow
            key={run.runId}
            data-run={run.runId}
            data-trigger={run.trigger ?? "unknown"}
            data-status={run.status}
          >
            <TableCell className="align-top whitespace-nowrap">
              <time dateTime={run.startedAt}>{formatDateTime(run.startedAt)}</time>
              <span className="block text-xs text-fg-muted">
                {run.finishedAt === null ? (
                  t("pipeline.runs.notFinished")
                ) : (
                  <>
                    {t("pipeline.runs.finished")}{" "}
                    <time dateTime={run.finishedAt}>{formatDateTime(run.finishedAt)}</time>
                  </>
                )}
              </span>
            </TableCell>
            {showSource ? (
              <TableCell className="align-top">
                {run.sourceKey === null ? (
                  t("common.unknown")
                ) : (
                  <Link
                    href={sourceHref(run.sourceKey) as Route}
                    className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                  >
                    {run.sourceKey}
                  </Link>
                )}
              </TableCell>
            ) : null}
            <TableCell className="align-top">
              {run.trigger === "backfill" ? (
                <Badge tone="info" data-slot="backfill-badge">
                  {runTriggerLabel(run.trigger)}
                </Badge>
              ) : (
                runTriggerLabel(run.trigger)
              )}
            </TableCell>
            <TableCell className="align-top">
              <StatusChip
                status={run.status}
                tone={runStatusTone(run.status)}
                label={runStatusLabel(run.status)}
              />
              {run.error === "" ? null : (
                <span className="mt-1 block max-w-md text-xs whitespace-normal text-danger">
                  {run.error}
                </span>
              )}
            </TableCell>
            <TableCell className="align-top text-sm">
              {t("pipeline.runs.counts", {
                listed: run.listed,
                stored: run.stored,
                duplicates: run.duplicates,
                failed: run.failed,
              })}
            </TableCell>
            <TableCell className="align-top">
              {run.workflowId === null ? (
                <span className="text-sm text-fg-muted">{t("pipeline.runs.noWorkflow")}</span>
              ) : (
                <code className="font-mono text-xs break-all">{run.workflowId}</code>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
