import "server-only";

import type { DocumentDetail } from "@/entities/pipeline/types";
import type { RelationCandidate, RulebookDocument } from "@/entities/rulebook/types";
import type { ReviewTaskDetail, RuleVersion } from "@/entities/rule-version/types";
import {
  rulebookWorkflowAccess,
  rulebookWriteAccess,
  type WriteAccess,
} from "@/server/api/rulebook-write";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { getOntology, readOntology } from "@/server/ontology";
import { err, ok, type ApiError, type Result } from "@/server/result";
import { reviewTasksGateway } from "./gateway";
import { QUEUE_PAGE_SIZE, queueView, type QueueFilter, type QueueView } from "./model/queue";
import { statsStrip, statsView, type StatsStrip, type StatsView } from "./model/stats";
import {
  relationChoices,
  sourceDocumentIds,
  workbenchView,
  type WorkbenchReads,
  type WorkbenchView,
} from "./model/workbench";
import type { ReviewTasksPort } from "./ports";
import type { AccessView, RelationChoice } from "./ui/form-shared";

/**
 * The review screens' reads. The queue reads one page of tasks and the stats (for the strip and
 * the regulators the chips offer) side by side, each with its own failure; the stats page reads
 * the stats; the workbench reads the task, then side by side the ontology, each document it shows
 * with the pipeline's record of its file, the rule's versions (for the previous one), the write
 * access, and for a candidate's draft form the document's open relation candidates, the rules and
 * the versions a relation may point at (`relationReads`), which the draft action reads again to
 * check what it is sent against.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

function accessView(access: WriteAccess): AccessView {
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
  };
}

export interface QueuePage {
  /** The page of tasks; an error when the queue could not be read. */
  queue: Result<QueueView>;
  /** Whether the session may claim and open the seed tasks, and why not. */
  access: AccessView;
  /** The strip; an error when the stats could not be read (the queue still shows). */
  strip: Result<StatsStrip>;
  /** The regulators the stats count, for the chips; empty when they could not be read. */
  regulators: string[];
}

export async function getQueuePage(
  session: ClientPrincipal,
  filter: QueueFilter,
  deps: QueryDeps = {},
): Promise<QueuePage> {
  const port = reviewTasksGateway(deps);
  const [tasks, stats, access] = await Promise.all([
    port.tasks({
      status: filter.status === "all" ? null : filter.status,
      regulator: filter.regulator,
      kind: filter.kind,
      cursor: filter.cursor,
      limit: QUEUE_PAGE_SIZE,
    }),
    port.stats(),
    rulebookWriteAccess({ session, fetchImpl: deps.fetchImpl }),
  ]);
  return {
    queue: tasks.ok
      ? ok(queueView(filter, tasks.value.tasks, tasks.value.nextCursor, session.userId))
      : tasks,
    access: accessView(access),
    strip: stats.ok ? ok(statsStrip(stats.value)) : stats,
    regulators: stats.ok ? stats.value.byRegulator.map((row) => row.regulator) : [],
  };
}

export async function getStatsPage(deps: QueryDeps = {}): Promise<Result<StatsView>> {
  const stats = await reviewTasksGateway(deps).stats();
  return stats.ok ? ok(statsView(stats.value)) : stats;
}

/** These rules' versions; a rule gone between the reads is skipped. */
async function versionsOfRules(
  port: ReviewTasksPort,
  ruleKeys: readonly string[],
): Promise<Result<RuleVersion[]>> {
  const versions = await Promise.all(ruleKeys.map((key) => port.versionsOf(key)));
  const all: RuleVersion[] = [];
  for (const result of versions) {
    if (result.ok) all.push(...result.value);
    else if (result.error.kind !== "not_found") return err(result.error);
  }
  return ok(all);
}

/** Every rule's versions. */
async function everyVersion(port: ReviewTasksPort): Promise<Result<RuleVersion[]>> {
  const rules = await port.rules();
  if (!rules.ok) return rules;
  return versionsOfRules(
    port,
    rules.value.map((rule) => rule.ruleKey),
  );
}

export interface RelationReads {
  relations: Result<RelationCandidate[]>;
  /** The versions they may point at; null when there is no relation candidate to offer. */
  targets: Result<RuleVersion[]> | null;
}

/**
 * What the draft form offers to take on: the open relation candidates of the candidate's document
 * and the versions each may point at. When every candidate names the rule it targets, only those
 * rules' versions are read (one read per rule named); a candidate that names none may point at
 * any rule's version, and then every rule's versions are read.
 */
export async function relationReads(
  port: ReviewTasksPort,
  documentId: string,
): Promise<RelationReads> {
  const relations = await port.openRelations(documentId);
  if (!relations.ok || relations.value.length === 0) return { relations, targets: null };
  const keys = relations.value.map((relation) => relation.targetRuleKey);
  const named = keys.filter((key): key is string => key !== null);
  const targets =
    named.length === keys.length
      ? await versionsOfRules(port, [...new Set(named)])
      : await everyVersion(port);
  return { relations, targets };
}

export interface OfferedRelations {
  /** What the form offers for each candidate. */
  choices: RelationChoice[];
  /** The candidates themselves, for the words a refusal names one by. */
  candidates: RelationCandidate[];
}

/**
 * The relation candidates a claimed candidate task's draft may take on, read again when the draft
 * is sent, to check the form against (D-061); none for a task without a candidate.
 */
export async function relationsOffered(
  taskId: string,
  deps: QueryDeps = {},
): Promise<Result<OfferedRelations>> {
  const port = reviewTasksGateway(deps);
  const task = await port.task(taskId);
  if (!task.ok) return task;
  const candidate = task.value.candidate;
  if (candidate === null) return ok({ choices: [], candidates: [] });
  const reads = await relationReads(port, candidate.documentId);
  if (!reads.relations.ok) return reads.relations;
  if (reads.targets !== null && !reads.targets.ok) return reads.targets;
  return ok({
    choices: relationChoices(reads.relations.value, reads.targets?.value ?? []),
    candidates: reads.relations.value,
  });
}

async function readEach<T>(
  ids: readonly string[],
  read: (id: string) => Promise<Result<T>>,
): Promise<Map<string, Result<T>>> {
  const results = await Promise.all(ids.map(read));
  return new Map(ids.map((id, index) => [id, results[index] as Result<T>]));
}

/**
 * The workbench of one task, or null for a task the rulebook does not hold. The draft form's
 * extra reads (relations, rules, versions) are made only when the form is shown: a candidate task
 * not drafted yet, claimed by the signed-in analyst.
 */
export async function getWorkbench(
  session: ClientPrincipal,
  taskId: string,
  deps: QueryDeps = {},
): Promise<Result<WorkbenchView | null>> {
  const port = reviewTasksGateway(deps);
  const read = await port.task(taskId);
  if (!read.ok) return read.error.kind === "not_found" ? ok(null) : read;
  const view = await workbenchFor(session, read.value, port, deps);
  return ok(view);
}

export async function workbenchFor(
  session: ClientPrincipal,
  detail: ReviewTaskDetail,
  port: ReviewTasksPort,
  deps: QueryDeps = {},
): Promise<WorkbenchView> {
  const documentIds = sourceDocumentIds(detail);
  const candidate = detail.candidate;
  const formShown =
    candidate !== null &&
    detail.version === null &&
    detail.task.status !== "decided" &&
    detail.task.claimedBy === session.userId;
  const [ontology, documents, stored, ruleVersions, access, lifecycle, offered, rules] =
    await Promise.all([
      deps.fetchImpl === undefined ? getOntology() : readOntology({ fetchImpl: deps.fetchImpl }),
      readEach<RulebookDocument>(documentIds, (id) => port.document(id)),
      readEach<DocumentDetail>(documentIds, (id) => port.storedDocument(id)),
      detail.version === null ? Promise.resolve(null) : port.versionsOf(detail.version.ruleKey),
      rulebookWriteAccess({ session, fetchImpl: deps.fetchImpl }),
      rulebookWorkflowAccess({ session, fetchImpl: deps.fetchImpl }),
      formShown ? relationReads(port, candidate.documentId) : Promise.resolve(null),
      formShown ? port.rules() : Promise.resolve(null),
    ]);
  const reads: WorkbenchReads = {
    detail,
    ontology,
    documents,
    stored,
    ruleVersions,
    relations: offered?.relations ?? null,
    targets: offered?.targets ?? null,
    ruleKeys: rules !== null && rules.ok ? rules.value.map((rule) => rule.ruleKey).sort() : [],
    access: accessView(access),
    lifecycle: accessView(lifecycle),
  };
  return workbenchView(reads, session);
}

/** A task read again after a refusal, to say who holds or decided it; null when it is gone. */
export async function taskNow(
  taskId: string,
  deps: QueryDeps = {},
): Promise<Result<ReviewTaskDetail | null>> {
  const read = await reviewTasksGateway(deps).task(taskId);
  if (read.ok) return read;
  return read.error.kind === "not_found" ? ok(null) : err<ApiError>(read.error);
}
