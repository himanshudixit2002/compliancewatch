import "server-only";

import type { ClauseDetail, RuleRelation } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { rulebookWorkflowAccess } from "@/server/api/rulebook-write";
import type { ClientContext } from "@/server/api/services";
import { getOntology } from "@/server/ontology";
import { ok, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { describeSpecification } from "@/shared/ui/specification";
import { ruleVersionsGateway } from "./gateway";
import { listHref, type VersionListFilter } from "./model/list-filter";
import {
  PAGE_SIZE,
  RULE_BATCH,
  byRuleKey,
  inStatus,
  ruleOptions,
  versionRow,
  type VersionListView,
} from "./model/version-list";
import { citationView, graphHref, relationView, type VersionPageView } from "./model/version-page";
import { stepsOffered } from "./model/workflow";
import type { RuleVersionsPort } from "./ports";
import type { AccessView } from "./ui/workflow-shared";

type Deps = { fetchImpl?: ClientContext["fetchImpl"]; port?: RuleVersionsPort };

function portOf(deps: Deps): RuleVersionsPort {
  return deps.port ?? ruleVersionsGateway({ fetchImpl: deps.fetchImpl });
}

/** At most this many versions at the other end of the relations are read for their names. */
export const RELATED_VERSION_READS = 50;

function listPath(): string {
  return hrefFor(screenById("admin.rulebook.versions"));
}

/**
 * The in-force list: the rulebook's own as-of read, one version per rule, ordered and paged by
 * rule key. One more row than a page is asked for, to know whether a next page exists.
 */
async function inForcePage(
  port: RuleVersionsPort,
  filter: VersionListFilter,
): Promise<Result<{ versions: RuleVersion[]; next: string | null }>> {
  const read = await port.inForce({
    asOf: filter.asOf,
    limit: PAGE_SIZE + 1,
    ...(filter.ruleKey === null ? {} : { ruleKey: filter.ruleKey }),
    ...(filter.after === null ? {} : { after: filter.after }),
  });
  if (!read.ok) return read;
  const versions = read.value.slice(0, PAGE_SIZE);
  const last = versions.at(-1);
  return ok({
    versions,
    next: read.value.length > PAGE_SIZE && last !== undefined ? last.ruleKey : null,
  });
}

/**
 * A status list: each rule's versions (the only read that returns drafts), rule by rule from the
 * cursor, a few rules at a time, until a page is full or the rules run out. The cursor is the
 * last rule read, so the next page continues after it as the in-force list does.
 */
async function statusPage(
  port: RuleVersionsPort,
  keys: readonly string[],
  filter: VersionListFilter & { status: Exclude<VersionListFilter["status"], "in_force"> },
): Promise<Result<{ versions: RuleVersion[]; next: string | null }>> {
  const after = filter.after;
  const remaining = keys.filter((key) => after === null || key > after);
  const versions: RuleVersion[] = [];
  let lastRead: string | null = null;
  for (
    let start = 0;
    start < remaining.length && versions.length < PAGE_SIZE;
    start += RULE_BATCH
  ) {
    const batch = remaining.slice(start, start + RULE_BATCH);
    const reads = await Promise.all(batch.map((key) => port.versionsOf(key)));
    for (const read of reads) {
      // A rule that went away between the two reads has nothing to list.
      if (!read.ok && read.error.kind !== "not_found") return read;
      if (read.ok) versions.push(...inStatus(read.value, filter.status));
    }
    lastRead = batch.at(-1) ?? lastRead;
  }
  const more = lastRead !== null && remaining.at(-1) !== lastRead;
  return ok({ versions, next: more ? lastRead : null });
}

/** The rule version list for a filter: the rows, the way to the next page and the rule choices. */
export async function getVersionList(
  filter: VersionListFilter,
  deps: Deps = {},
): Promise<Result<VersionListView>> {
  const port = portOf(deps);
  const rules = await port.rules();
  if (!rules.ok) return rules;
  const keys = [...rules.value]
    .sort(byRuleKey)
    .map((rule) => rule.ruleKey)
    .filter((key) => filter.ruleKey === null || key === filter.ruleKey);
  const page =
    filter.status === "in_force"
      ? await inForcePage(port, filter)
      : await statusPage(port, keys, { ...filter, status: filter.status });
  if (!page.ok) return page;
  const path = listPath();
  return ok({
    filter,
    rows: page.value.versions.map(versionRow),
    nextHref: page.value.next === null ? null : listHref(path, filter, page.value.next),
    firstHref: filter.after === null ? null : listHref(path, filter),
    rules: ruleOptions(rules.value),
  });
}

function accessView(access: Awaited<ReturnType<typeof rulebookWorkflowAccess>>): AccessView {
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
    flag: access.flag,
  };
}

async function clausesOf(
  port: RuleVersionsPort,
  clauseIds: readonly string[],
): Promise<Map<string, ClauseDetail>> {
  const unique = [...new Set(clauseIds)];
  const reads = await Promise.all(unique.map((clauseId) => port.clause(clauseId)));
  const found = new Map<string, ClauseDetail>();
  reads.forEach((read, index) => {
    if (read.ok) found.set(unique[index] as string, read.value);
  });
  return found;
}

async function versionsOf(
  port: RuleVersionsPort,
  relations: readonly RuleRelation[],
  self: string,
): Promise<Map<string, RuleVersion>> {
  const ids = new Set<string>();
  for (const relation of relations) {
    for (const id of [relation.fromRuleVersionId, relation.toRuleVersionId]) {
      if (id !== null && id !== self) ids.add(id);
    }
  }
  const wanted = [...ids].slice(0, RELATED_VERSION_READS);
  const reads = await Promise.all(wanted.map((id) => port.version(id)));
  const found = new Map<string, RuleVersion>();
  reads.forEach((read, index) => {
    if (read.ok) found.set(wanted[index] as string, read.value);
  });
  return found;
}

/**
 * The version page: the version first (a version the rulebook does not hold is the caller's
 * not-found), then, side by side, its citations, its relations from and to it, the ontology to
 * word its condition with, and whether the session may take workflow steps (and which: approving,
 * publishing and withdrawing are left to a reviewer or an admin); then the clauses the citations
 * cite and the versions at the other end of the relations, for their names.
 */
export async function getVersionPage(
  ruleVersionId: string,
  ctx: Pick<ClientContext, "session">,
  deps: Deps & { ontology?: typeof getOntology } = {},
): Promise<Result<VersionPageView>> {
  const port = portOf(deps);
  const version = await port.version(ruleVersionId);
  if (!version.ok) return version;
  const [citations, from, to, ontology, access] = await Promise.all([
    port.citations(ruleVersionId),
    port.relations({ from: ruleVersionId }),
    port.relations({ to: ruleVersionId }),
    (deps.ontology ?? getOntology)(),
    rulebookWorkflowAccess({ session: ctx.session, fetchImpl: deps.fetchImpl }),
  ]);
  const clauses = citations.ok
    ? await clausesOf(
        port,
        citations.value.map((citation) => citation.clauseId),
      )
    : new Map<string, ClauseDetail>();
  const related =
    from.ok && to.ok
      ? await versionsOf(port, [...from.value, ...to.value], ruleVersionId)
      : new Map();
  const relations: VersionPageView["relations"] = !from.ok
    ? { ok: false, error: from.error }
    : !to.ok
      ? { ok: false, error: to.error }
      : {
          ok: true,
          value: {
            from: from.value.map((relation) => relationView(relation, "from", related)),
            to: to.value.map((relation) => relationView(relation, "to", related)),
          },
        };
  const spec = version.value.specification;
  const { steps, reserved } = stepsOffered(version.value.status, ctx.session);
  return ok({
    version: version.value,
    specification:
      spec === null ? null : describeSpecification(spec, ontology.ok ? ontology.value : null),
    ontologyError: ontology.ok ? null : ontology.error,
    citations: citations.ok
      ? {
          ok: true,
          value: citations.value.map((citation) =>
            citationView(citation, clauses.get(citation.clauseId) ?? null),
          ),
        }
      : { ok: false, error: citations.error },
    relations,
    steps,
    reserved,
    access: accessView(access),
    canCite: version.value.status === "draft",
    graphHref: graphHref(ruleVersionId),
  });
}
