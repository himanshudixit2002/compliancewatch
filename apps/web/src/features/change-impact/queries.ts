import "server-only";

import type { Business } from "@/entities/business/types";
import type { ClientContext } from "@/server/api/services";
import { ok, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import { changeImpactGateway, type ChangeImpactGateway } from "./gateway";
import {
  IMPACT_PAGE_SIZE,
  clientRows,
  countsView,
  fanOutLine,
  impactHref,
  nodeLabel,
  type ClientRow,
  type CountsView,
  type ResultFilter,
} from "./model/impact";
import { MAX_BULK_BUSINESSES, type BulkTarget } from "./ui/bulk-shared";

/**
 * The affected clients screen's read, for the session's tenant (a CA firm): the change from the
 * rulebook (an id the rulebook does not hold is the not-found page), a page of the impact's
 * clients with the chosen result, each client's name from the profile service (read in parallel;
 * a client the service does not answer for keeps its id), and the businesses a bulk change card
 * would name: every business whose latest decision applies, walked from the impact's pages of
 * 200 clients up to five pages, at most 500 (the route's limit; the page says when there are more).
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

/** The impact's largest page of clients, and how many pages the walk for the bulk card takes. */
const WALK_PAGE = 200;
const MAX_WALK_PAGES = 5;

export interface ChangeImpactView {
  ruleVersionId: string;
  /** "example_rule v2" and its title. */
  name: string;
  title: string;
  status: string;
  counts: CountsView;
  fanOut: string;
  filter: ResultFilter;
  clients: readonly ClientRow[];
  nextHref: string | null;
  firstHref: string | null;
  /** The affected businesses the bulk change card names, with their words. */
  targets: readonly BulkTarget[];
  /** True when more businesses are affected than one card names, or the walk stopped short. */
  targetsCut: boolean;
}

async function namesOf(
  gateway: ChangeImpactGateway,
  entityIds: readonly string[],
): Promise<Map<string, Business>> {
  const unique = [...new Set(entityIds)];
  const read = await Promise.all(unique.map((id) => gateway.business(id)));
  const names = new Map<string, Business>();
  for (const business of read) if (business.ok) names.set(business.value.id, business.value);
  return names;
}

/** Every affected business, walked from the impact's pages, with the names the page knows. */
async function affected(
  gateway: ChangeImpactGateway,
  ruleVersionId: string,
  names: ReadonlyMap<string, Business>,
): Promise<{ targets: BulkTarget[]; cut: boolean }> {
  const targets = new Map<string, BulkTarget>();
  let cursor: string | undefined;
  for (let page = 0; page < MAX_WALK_PAGES; page += 1) {
    const impact = await gateway.impact(ruleVersionId, {
      result: "applies",
      limit: WALK_PAGE,
      ...(cursor === undefined ? {} : { cursor }),
    });
    if (!impact.ok) return { targets: [...targets.values()], cut: true };
    for (const client of impact.value.clients) {
      const business = names.get(client.entityId) ?? null;
      for (const row of client.businesses) {
        if (row.result !== "applies") continue;
        targets.set(row.businessId, {
          businessId: row.businessId,
          label:
            business === null
              ? row.businessId
              : t("changeImpact.target", {
                  client: business.name,
                  node: nodeLabel(business, row.businessId),
                }),
        });
      }
    }
    if (impact.value.nextCursor === null) {
      const all = [...targets.values()];
      return { targets: all.slice(0, MAX_BULK_BUSINESSES), cut: all.length > MAX_BULK_BUSINESSES };
    }
    cursor = impact.value.nextCursor;
  }
  return { targets: [...targets.values()].slice(0, MAX_BULK_BUSINESSES), cut: true };
}

export async function getChangeImpact(
  session: QuerySession,
  ruleVersionId: string,
  query: { result: ResultFilter; cursor: string | null },
  deps: QueryDeps = {},
): Promise<Result<ChangeImpactView>> {
  const gateway = changeImpactGateway({ session, fetchImpl: deps.fetchImpl });
  const [version, impact] = await Promise.all([
    gateway.version(ruleVersionId),
    gateway.impact(ruleVersionId, {
      limit: IMPACT_PAGE_SIZE,
      ...(query.result === "all" ? {} : { result: query.result }),
      ...(query.cursor === null ? {} : { cursor: query.cursor }),
    }),
  ]);
  if (!version.ok) return version;
  if (!impact.ok) return impact;
  const names = await namesOf(
    gateway,
    impact.value.clients.map((client) => client.entityId),
  );
  const bulk = await affected(gateway, ruleVersionId, names);
  const pathname = hrefFor(screenById("ca.change-impact"), { ruleVersionId });
  const { nextCursor } = impact.value;
  return ok({
    ruleVersionId,
    name: t("changeImpact.versionName", {
      rule: version.value.ruleKey,
      version: version.value.version,
    }),
    title: version.value.title,
    status: ruleVersionStatusLabel(version.value.status),
    counts: countsView(impact.value.counts),
    fanOut: fanOutLine(impact.value.fanOut),
    filter: query.result,
    clients: clientRows(impact.value, names),
    nextHref: nextCursor === null ? null : impactHref(pathname, query.result, nextCursor),
    firstHref: query.cursor === null ? null : impactHref(pathname, query.result),
    targets: bulk.targets,
    targetsCut: bulk.cut,
  });
}
