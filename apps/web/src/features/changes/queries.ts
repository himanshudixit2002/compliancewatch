import "server-only";

import type { Business } from "@/entities/business/types";
import type { ImpactBusiness } from "@/entities/applicability/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import type { ClientContext } from "@/server/api/services";
import { ok, type Result } from "@/server/result";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  CHANGES_PAGE_SIZE,
  applicabilityView,
  changeCard,
  feedHrefs,
  type ChangeCardView,
  type ImpactForBusiness,
} from "./model/changes";
import { changesGateway, type ChangesGateway } from "./gateway";

/**
 * The changes screen's read: a page of the rulebook's feed, newest first, and for each change
 * whether it applies to this business. The impact route lists the tenant's clients a page at a
 * time in entity order with no filter by client, so the read walks its pages until it meets this
 * business (a business tenant has one; a CA firm may have many) or runs out, and says so if it
 * could not get there.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

/** The impact route's largest page of clients, and how many pages one change may take. */
const IMPACT_PAGE = 200;
const MAX_IMPACT_PAGES = 5;

export interface BusinessRef {
  id: string;
  name: string;
  pan: string;
}

export interface ChangesView {
  business: BusinessRef;
  cards: readonly ChangeCardView[];
  nextHref: string | null;
  firstHref: string | null;
}

/** The business's nodes by id, named by PAN or GSTIN with their name. */
function nodeNames(business: Business): (nodeId: string) => string {
  const names = new Map<string, string>([
    [business.id, t("business.node.entity", { key: business.pan, name: business.name })],
    ...business.registrations.map(
      (node) =>
        [node.id, t("business.node.registration", { key: node.key, name: node.name })] as const,
    ),
  ]);
  return (nodeId) => names.get(nodeId) ?? t("changes.otherNode", { id: nodeId.slice(0, 8) });
}

async function impactFor(
  gateway: ChangesGateway,
  ruleVersionId: string,
  businessId: string,
): Promise<ImpactForBusiness> {
  let cursor: string | undefined;
  for (let page = 0; page < MAX_IMPACT_PAGES; page += 1) {
    const impact = await gateway.impact(ruleVersionId, {
      limit: IMPACT_PAGE,
      ...(cursor === undefined ? {} : { cursor }),
    });
    if (!impact.ok) {
      return {
        state: "failed",
        message: impact.error.message,
        correlationId: impact.error.requestId === "" ? null : impact.error.requestId,
      };
    }
    const client = impact.value.clients.find((candidate) => candidate.entityId === businessId);
    if (client !== undefined) return { state: "read", businesses: client.businesses };
    if (impact.value.nextCursor === null)
      return { state: "read", businesses: [] as ImpactBusiness[] };
    cursor = impact.value.nextCursor;
  }
  return { state: "failed", message: t("changes.tooManyClients"), correlationId: null };
}

export async function getChanges(
  session: QuerySession,
  businessId: string,
  cursor: string | null,
  deps: QueryDeps = {},
): Promise<Result<ChangesView>> {
  const gateway = changesGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, feed] = await Promise.all([
    gateway.business(businessId),
    gateway.feed({ limit: CHANGES_PAGE_SIZE, ...(cursor === null ? {} : { cursor }) }),
  ]);
  if (!business.ok) return business;
  if (!feed.ok) return feed;
  const versions = [...new Set(feed.value.items.map((change) => change.ruleVersionId))];
  const clauseIds = [
    ...new Set(feed.value.items.flatMap((change) => change.citations.map((c) => c.clauseId))),
  ];
  const [impacts, clauses] = await Promise.all([
    Promise.all(versions.map((version) => impactFor(gateway, version, businessId))),
    Promise.all(clauseIds.map((id) => gateway.clause(id))),
  ]);
  const impactOf = new Map(versions.map((version, index) => [version, impacts[index]]));
  const clauseMap = new Map<string, ClauseDetail>();
  for (const clause of clauses) if (clause.ok) clauseMap.set(clause.value.clauseId, clause.value);
  const names = nodeNames(business.value);
  const pathname = hrefFor(screenById("owner.changes"), { businessId });
  // A CA firm's people may open every client a change affects; nobody else sees the link.
  const impactScreen = screenById("ca.change-impact");
  const offersImpact = isVisibleTo(impactScreen, session.roles, session.tenantKind);
  return ok({
    business: { id: business.value.id, name: business.value.name, pan: business.value.pan },
    cards: feed.value.items.map((change) =>
      changeCard(change, {
        clauses: clauseMap,
        applicability: applicabilityView(
          impactOf.get(change.ruleVersionId) ?? { state: "read", businesses: [] },
          names,
        ),
        impactHref: offersImpact
          ? hrefFor(impactScreen, { ruleVersionId: change.ruleVersionId })
          : null,
      }),
    ),
    ...feedHrefs(pathname, cursor, feed.value.nextCursor),
  });
}
