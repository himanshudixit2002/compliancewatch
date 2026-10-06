import type { Tone } from "@compliancewatch/ui";
import {
  DOCUMENT_TYPES,
  RELEVANCES,
  TASK_KINDS,
  TASK_STATUSES,
  type DocumentType,
  type Page,
  type PipelineTask,
  type Relevance,
  type TaskKind,
  type TaskStatus,
  type TriageDecision,
} from "@/entities/pipeline/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";
import type { FilterChip } from "@/shared/ui/filter-chips";
import { sourceHref } from "@/shared/ui/pipeline";
import { RESOLVE_FIELDS, TRANSCRIPT_TITLE_MAX } from "../ui/pipeline-shared";
import { readTranscript } from "../ui/transcript";
import { documentPageHref, documentTitle } from "./operations";
import { reasonOf } from "./document";

/**
 * The pipeline's tasks: the work people do on stored documents. A manual parse opens when no
 * parser reads a document (a scan without a text layer): an analyst types it in and the pipeline
 * parses that. A triage opens when the classify step finds the document's text naming another
 * type than its source publishes: a person decides whether it is relevant and what it is. The
 * list is the pipeline's, oldest first, by status (open by default) and kind, a page at a time;
 * the query holds the filters and the cursor.
 */
export const TASK_PARAMS = { status: "status", kind: "kind", cursor: "cursor" } as const;

export const TASK_PAGE_SIZE = 25;

/** `every` lists every status or every kind. */
export const EVERY = "every";

export interface TaskFilter {
  status: TaskStatus | null;
  kind: TaskKind | null;
  cursor: string | null;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

export function readTaskQuery(query: Query): TaskFilter {
  const status = first(query, TASK_PARAMS.status);
  const kind = first(query, TASK_PARAMS.kind);
  const cursor = first(query, TASK_PARAMS.cursor);
  return {
    status:
      status === EVERY
        ? null
        : (TASK_STATUSES as readonly string[]).includes(status)
          ? (status as TaskStatus)
          : "open",
    kind: (TASK_KINDS as readonly string[]).includes(kind) ? (kind as TaskKind) : null,
    cursor: cursor === "" || cursor.length > 512 ? null : cursor,
  };
}

export function tasksHref(filter: TaskFilter, cursor: string | null = null): string {
  return withQuery(hrefFor(screenById("admin.pipeline.tasks")), {
    [TASK_PARAMS.status]: filter.status === "open" ? undefined : (filter.status ?? EVERY),
    [TASK_PARAMS.kind]: filter.kind ?? undefined,
    [TASK_PARAMS.cursor]: cursor ?? undefined,
  });
}

const STATUS_LABELS: Readonly<Record<TaskStatus, MessageKey>> = {
  open: "pipelineTasks.status.open",
  resolved: "pipelineTasks.status.resolved",
  dismissed: "pipelineTasks.status.dismissed",
};

const STATUS_TONES: Readonly<Record<TaskStatus, Tone>> = {
  open: "warning",
  resolved: "success",
  dismissed: "neutral",
};

const KIND_LABELS: Readonly<Record<TaskKind, MessageKey>> = {
  manual_parse: "pipelineTasks.kind.manualParse",
  triage: "pipelineTasks.kind.triage",
};

export function taskStatusLabel(status: string): string {
  return Object.hasOwn(STATUS_LABELS, status)
    ? t(STATUS_LABELS[status as TaskStatus])
    : humanise(status);
}

export function taskKindLabel(kind: string): string {
  return Object.hasOwn(KIND_LABELS, kind) ? t(KIND_LABELS[kind as TaskKind]) : humanise(kind);
}

/** The status chips (open, resolved, dismissed, every), each keeping the kind. */
export function statusChips(filter: TaskFilter): FilterChip[] {
  return [...TASK_STATUSES, null].map((status) => ({
    key: status ?? EVERY,
    label: status === null ? t("pipelineTasks.status.every") : taskStatusLabel(status),
    href: tasksHref({ status, kind: filter.kind, cursor: null }),
    current: status === filter.status,
  }));
}

/** The kind chips (every kind, manual parse, triage), each keeping the status. */
export function kindChips(filter: TaskFilter): FilterChip[] {
  return [null, ...TASK_KINDS].map((kind) => ({
    key: kind ?? EVERY,
    label: kind === null ? t("pipelineTasks.kind.every") : taskKindLabel(kind),
    href: tasksHref({ status: filter.status, kind, cursor: null }),
    current: kind === filter.kind,
  }));
}

export interface TaskCard {
  taskId: string;
  kind: TaskKind;
  kindLabel: string;
  status: TaskStatus;
  statusLabel: string;
  statusTone: Tone;
  document: {
    documentId: string;
    title: string;
    externalRef: string;
    status: string;
    href: string;
    rawHref: string;
  };
  sourceKey: string;
  sourceHref: string;
  opened: string;
  openedIso: string;
  reason: string;
  claimedBy: string | null;
  closed: { by: string | null; at: string | null; atIso: string | null; note: string } | null;
  resolution: Readonly<Record<string, unknown>> | null;
}

function person(id: string | null, userId: string | null): string | null {
  if (id === null) return null;
  return id === userId ? t("adminPipeline.you") : id;
}

export function taskCard(task: PipelineTask, userId: string | null): TaskCard {
  return {
    taskId: task.taskId,
    kind: task.kind,
    kindLabel: taskKindLabel(task.kind),
    status: task.status,
    statusLabel: taskStatusLabel(task.status),
    statusTone: Object.hasOwn(STATUS_TONES, task.status) ? STATUS_TONES[task.status] : "neutral",
    document: {
      documentId: task.document.documentId,
      title: documentTitle(task.document),
      externalRef: task.document.externalRef,
      status: task.document.status,
      href: documentPageHref(task.document.documentId),
      rawHref: hrefFor(screenById("system.raw-document"), {
        documentId: task.document.documentId,
      }),
    },
    sourceKey: task.sourceKey,
    sourceHref: sourceHref(task.sourceKey),
    opened: formatDateTime(task.openedAt),
    openedIso: task.openedAt,
    reason: task.reason,
    claimedBy: person(task.claimedBy, userId),
    closed:
      task.status === "open"
        ? null
        : {
            by: person(task.resolvedBy, userId),
            at: task.resolvedAt === null ? null : formatDateTime(task.resolvedAt),
            atIso: task.resolvedAt,
            note: task.note,
          },
    resolution: task.resolution,
  };
}

export interface TasksView {
  filter: TaskFilter;
  cards: TaskCard[];
  nextHref: string | null;
  firstHref: string | null;
}

export function tasksView(
  filter: TaskFilter,
  page: Page<PipelineTask>,
  userId: string | null,
): TasksView {
  return {
    filter,
    cards: page.items.map((task) => taskCard(task, userId)),
    nextHref: page.nextCursor === null ? null : tasksHref(filter, page.nextCursor),
    firstHref: filter.cursor === null ? null : tasksHref(filter),
  };
}

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export type ParsedResolution =
  | {
      ok: true;
      resolution:
        | { transcript: { title: string; blocks: ReturnType<typeof readTranscript>["blocks"] } }
        | { triage: TriageDecision };
      reason: string;
    }
  | { ok: false; fieldErrors: FieldErrors };

/**
 * A resolution's form for the task's kind: a manual parse's transcript (its title and its text,
 * read as the panel reads it) or a triage's decision (relevant with a type, or irrelevant), with
 * the reason.
 */
export function parseResolution(kind: TaskKind, formData: FormData): ParsedResolution {
  const errors: Record<string, string[]> = {};
  const reason = reasonOf(formData, RESOLVE_FIELDS.reason);
  if (!reason.ok) Object.assign(errors, reason.fieldErrors);
  if (kind === "manual_parse") {
    const title = text(formData, RESOLVE_FIELDS.title).trim();
    if (title.length > TRANSCRIPT_TITLE_MAX) {
      errors[RESOLVE_FIELDS.title] = [
        t("pipelineTasks.error.titleLong", { max: TRANSCRIPT_TITLE_MAX }),
      ];
    }
    const read = readTranscript(text(formData, RESOLVE_FIELDS.transcript));
    if (!read.ok) errors[RESOLVE_FIELDS.transcript] = read.errors;
    if (!reason.ok || Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
    return {
      ok: true,
      resolution: { transcript: { title, blocks: read.blocks } },
      reason: reason.reason,
    };
  }
  const relevanceValue = text(formData, RESOLVE_FIELDS.relevance);
  const relevance = (RELEVANCES as readonly string[]).includes(relevanceValue)
    ? (relevanceValue as Relevance)
    : null;
  if (relevance === null) errors[RESOLVE_FIELDS.relevance] = [t("pipelineTasks.error.relevance")];
  const typeValue = text(formData, RESOLVE_FIELDS.docType);
  const docType = (DOCUMENT_TYPES as readonly string[]).includes(typeValue)
    ? (typeValue as DocumentType)
    : null;
  if (relevance === "relevant" && docType === null) {
    errors[RESOLVE_FIELDS.docType] = [t("pipelineTasks.error.type")];
  }
  if (!reason.ok || relevance === null || Object.keys(errors).length > 0) {
    return { ok: false, fieldErrors: errors };
  }
  return {
    ok: true,
    resolution: {
      triage:
        relevance === "relevant" && docType !== null
          ? { relevance: "relevant", docType }
          : { relevance: "irrelevant" },
    },
    reason: reason.reason,
  };
}
