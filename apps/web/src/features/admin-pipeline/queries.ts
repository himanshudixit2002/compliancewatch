import "server-only";

import { newIdempotencyKey } from "@/server/api/idempotency";
import { pipelineWriteAccess } from "@/server/api/pipeline-write";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { err, ok, type ApiError, type Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { t } from "@/shared/i18n";
import { pipelineGateway } from "./gateway";
import { documentPageView, type DocumentPageView } from "./model/document";
import {
  PIPELINE_PAGE_SIZE,
  documentRow,
  eventRow,
  pagedRows,
  type PipelineList,
  type PipelineRead,
} from "./model/operations";
import { TASK_PAGE_SIZE, tasksView, type TaskFilter, type TasksView } from "./model/tasks";
import type { PipelinePort } from "./ports";
import type { AccessView } from "./ui/pipeline-shared";

/**
 * The pipeline pages' reads: one view of the operations (runs, documents or the dead outbox) with
 * the sources' keys for its filter; a stored document with its retries; a page of tasks. Each says
 * whether the session may write there (an admin, with the write token set).
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
  port?: PipelinePort;
}

/** Whether the session may take the operations' writes, and why not: the role, then the token. */
export function controlAccess(session: ClientPrincipal, deps: QueryDeps = {}): AccessView {
  if (!can(session, "admin.pipeline.control")) {
    return { allowed: false, title: t("adminPipeline.access.adminOnly") };
  }
  const access = pipelineWriteAccess(
    { session, fetchImpl: deps.fetchImpl },
    "admin.pipeline.control",
  );
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
  };
}

export interface PipelinePage {
  read: PipelineRead;
  /** The view's rows; null when a filter field was refused or the read failed. */
  list: PipelineList | null;
  listError: ApiError | null;
  /** The sources' keys for the filter; null when they could not be read. */
  sourceKeys: string[] | null;
  access: AccessView;
}

export async function getPipelinePage(
  session: ClientPrincipal,
  read: PipelineRead,
  deps: QueryDeps = {},
): Promise<PipelinePage> {
  const port = deps.port ?? pipelineGateway(deps);
  const refused = Object.keys(read.invalid).length > 0;
  const current = read.current;
  const listRead = async (): Promise<Result<PipelineList> | null> => {
    if (refused) return null;
    if (current.view === "runs") {
      const { filter } = current;
      const page = await port.runs({
        sourceKey: filter.source,
        status: filter.status,
        trigger: filter.trigger,
        limit: PIPELINE_PAGE_SIZE,
        cursor: filter.cursor,
      });
      return page.ok
        ? ok({ view: "runs", list: pagedRows(current, page.value, (run) => run) })
        : page;
    }
    if (current.view === "documents") {
      const { filter } = current;
      const page = await port.documents({
        status: filter.status,
        sourceKey: filter.source,
        docType: filter.type,
        publishedFrom: filter.from,
        publishedTo: filter.to,
        limit: PIPELINE_PAGE_SIZE,
        cursor: filter.cursor,
      });
      return page.ok
        ? ok({
            view: "documents",
            list: pagedRows(current, page.value, (document) =>
              documentRow(document, session.userId),
            ),
          })
        : page;
    }
    const page = await port.deadEvents({
      topic: current.filter.topic,
      limit: PIPELINE_PAGE_SIZE,
      cursor: current.filter.cursor,
    });
    return page.ok ? ok({ view: "outbox", list: pagedRows(current, page.value, eventRow) }) : page;
  };
  const [list, keys] = await Promise.all([
    listRead(),
    current.view === "outbox" ? Promise.resolve(null) : port.sourceKeys(),
  ]);
  return {
    read,
    list: list !== null && list.ok ? list.value : null,
    listError: list !== null && !list.ok ? list.error : null,
    sourceKeys: keys !== null && keys.ok ? keys.value : null,
    access: controlAccess(session, deps),
  };
}

export interface DocumentPage {
  view: DocumentPageView;
  access: AccessView;
  /** The Idempotency-Key minted for this render of the retry form. */
  retryKey: string;
}

/** One stored document; null when the pipeline holds none under the id. */
export async function getDocumentPage(
  session: ClientPrincipal,
  documentId: string,
  deps: QueryDeps = {},
): Promise<Result<DocumentPage | null>> {
  const port = deps.port ?? pipelineGateway(deps);
  const document = await port.document(documentId);
  if (!document.ok) {
    return document.error.kind === "not_found" ? ok(null) : err(document.error);
  }
  return ok({
    view: documentPageView(document.value, session.userId),
    access: controlAccess(session, deps),
    retryKey: newIdempotencyKey(),
  });
}

export interface TasksPage {
  view: TasksView;
  access: AccessView;
}

export async function getTasksPage(
  session: ClientPrincipal,
  filter: TaskFilter,
  deps: QueryDeps = {},
): Promise<Result<TasksPage>> {
  const port = deps.port ?? pipelineGateway(deps);
  const page = await port.tasks({
    status: filter.status,
    kind: filter.kind,
    limit: TASK_PAGE_SIZE,
    cursor: filter.cursor,
  });
  if (!page.ok) return page;
  return ok({
    view: tasksView(filter, page.value, session.userId),
    access: controlAccess(session, deps),
  });
}
