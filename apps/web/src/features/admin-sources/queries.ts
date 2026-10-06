import "server-only";

import { REGISTRY } from "@compliancewatch/flags";
import type { CrawlRun } from "@/entities/pipeline/types";
import { pipelineWriteAccess } from "@/server/api/pipeline-write";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { getEnv } from "@/server/env";
import { err, ok, type ApiError, type Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { withQuery } from "@/shared/lib/url";
import { sourcesGateway } from "./gateway";
import {
  DOCUMENT_PAGE_SIZE,
  SOURCE_RUNS_SHOWN,
  documentsView,
  settingsDefaults,
  sourceFacts,
  type DocumentsView,
  type SourceFacts,
} from "./model/source";
import { runSummary, sourcesView, type CrawlFlag, type SourcesView } from "./model/sources";
import type { AccessView, SettingsDefaults } from "./ui/source-shared";

/**
 * The source pages' reads. The list reads every source and the schedule's latest crawl (one run
 * with the trigger `schedule`); a source's page reads the list for its record (the pipeline has no
 * read of one source), a page of its documents and its latest runs, in parallel, each of the last
 * two with its own error, and says whether the session may change the source.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

/** The crawl switch as packages/flags/registry.json declares it; the pipeline holds its value. */
export const CRAWL_FLAG_NAME = "pipeline.crawl";

export function crawlFlag(): CrawlFlag {
  const flag = REGISTRY.get(CRAWL_FLAG_NAME);
  return {
    name: flag.name,
    variable: flag.env ?? "",
    defaultOn: flag.default === true,
    owner: flag.owner,
  };
}

export async function getSourcesPage(deps: QueryDeps = {}): Promise<Result<SourcesView>> {
  const port = sourcesGateway(deps);
  const [sources, scheduled] = await Promise.all([
    port.sources(),
    port.runs({ sourceKey: null, status: null, trigger: "schedule", limit: 1, cursor: null }),
  ]);
  if (!sources.ok) return sources;
  const latest = scheduled.ok ? scheduled.value.items[0] : undefined;
  return ok(
    sourcesView(sources.value, {
      flag: crawlFlag(),
      latestScheduled: !scheduled.ok
        ? {
            kind: "error",
            message: scheduled.error.message,
            correlationId: scheduled.error.requestId === "" ? null : scheduled.error.requestId,
          }
        : latest === undefined
          ? { kind: "none" }
          : { kind: "run", sourceKey: latest.sourceKey, summary: runSummary(latest) },
    }),
  );
}

/** Whether the session may change sources, and why not: the role, then the token. */
export function sourceWriteAccess(session: ClientPrincipal, deps: QueryDeps = {}): AccessView {
  if (!can(session, "admin.sources.write")) {
    return { allowed: false, title: t("adminSources.access.adminOnly") };
  }
  const access = pipelineWriteAccess({ session, fetchImpl: deps.fetchImpl }, "admin.sources.write");
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
  };
}

export interface SourcePage {
  facts: SourceFacts;
  settings: SettingsDefaults;
  documents: DocumentsView | null;
  documentsError: ApiError | null;
  runs: CrawlRun[] | null;
  runsError: ApiError | null;
  /** The pipeline page's runs of this source, every one of them. */
  everyRunHref: string;
  access: AccessView;
  /** The upload handler for this source, and the largest file it forwards. */
  upload: { href: string; maxBytes: number };
  crawlFlag: CrawlFlag;
}

/** One source's page; null when the pipeline holds no source under the key. */
export async function getSourcePage(
  session: ClientPrincipal,
  key: string,
  cursor: string | null,
  deps: QueryDeps = {},
): Promise<Result<SourcePage | null>> {
  const port = sourcesGateway(deps);
  const [sources, documents, runs] = await Promise.all([
    port.sources(),
    port.documents(key, cursor, DOCUMENT_PAGE_SIZE),
    port.runs({
      sourceKey: key,
      status: null,
      trigger: null,
      limit: SOURCE_RUNS_SHOWN,
      cursor: null,
    }),
  ]);
  if (!sources.ok) return err(sources.error);
  const source = sources.value.find((candidate) => candidate.key === key);
  if (source === undefined) return ok(null);
  const pathname = hrefFor(screenById("admin.source"), { key });
  return ok({
    facts: sourceFacts(source),
    settings: settingsDefaults(source),
    documents: documents.ok ? documentsView(pathname, cursor, documents.value) : null,
    documentsError: documents.ok ? null : documents.error,
    runs: runs.ok ? [...runs.value.items] : null,
    runsError: runs.ok ? null : runs.error,
    everyRunHref: withQuery(hrefFor(screenById("admin.pipeline")), { view: "runs", source: key }),
    access: sourceWriteAccess(session, deps),
    upload: {
      href: hrefFor(screenById("system.uploads"), { key }),
      maxBytes: getEnv().CW_WEB_PIPELINE_UPLOAD_MAX_BYTES,
    },
    crawlFlag: crawlFlag(),
  });
}
