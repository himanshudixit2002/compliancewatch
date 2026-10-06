import "server-only";

import type { RuleVersion } from "@/entities/rule-version/types";
import type { ClientContext } from "@/server/api/services";
import { ok, type Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { decisionReviewGateway } from "./gateway";
import { REVIEW_PAGE_SIZE, reviewItemView, type ReviewItemView } from "./model/items";
import { lookupHref, type StatusFilter } from "./model/lookup";

/**
 * The decision review's read: one tenant's review items of a status, a page at a time with the
 * engine's cursor, each with the version it is about named from the rulebook (read once per
 * version on the page, in parallel; a version the rulebook does not answer for keeps its id). The
 * session decides only what the page offers: every regulatory role reads, a reviewer or an admin
 * settles (`admin.decisions.resolve`).
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

export interface DecisionsView {
  tenantId: string;
  status: StatusFilter;
  items: readonly ReviewItemView[];
  canResolve: boolean;
  nextHref: string | null;
  firstHref: string | null;
}

export async function getReviewItems(
  session: QuerySession,
  lookup: { tenantId: string; status: StatusFilter; cursor: string | null },
  deps: QueryDeps = {},
): Promise<Result<DecisionsView>> {
  const gateway = decisionReviewGateway({
    session,
    tenantId: lookup.tenantId,
    fetchImpl: deps.fetchImpl,
  });
  const page = await gateway.items({
    limit: REVIEW_PAGE_SIZE,
    ...(lookup.status === "all" ? {} : { status: lookup.status }),
    ...(lookup.cursor === null ? {} : { cursor: lookup.cursor }),
  });
  if (!page.ok) return page;
  const ids = [...new Set(page.value.items.map((item) => item.ruleVersionId))];
  const versions = await Promise.all(ids.map((id) => gateway.version(id)));
  const named = new Map<string, RuleVersion>();
  for (const version of versions) {
    if (version.ok) named.set(version.value.ruleVersionId, version.value);
  }
  const versionPage = screenById("admin.rulebook.version");
  const pathname = hrefFor(screenById("admin.decisions"));
  const { nextCursor } = page.value;
  return ok({
    tenantId: lookup.tenantId,
    status: lookup.status,
    items: page.value.items.map((item) =>
      reviewItemView(item, {
        version: named.get(item.ruleVersionId) ?? null,
        versionHref: hrefFor(versionPage, { ruleVersionId: item.ruleVersionId }),
        viewerId: session.userId,
      }),
    ),
    canResolve: can(session, "admin.decisions.resolve"),
    nextHref:
      nextCursor === null ? null : lookupHref(pathname, lookup.tenantId, lookup.status, nextCursor),
    firstHref: lookup.cursor === null ? null : lookupHref(pathname, lookup.tenantId, lookup.status),
  });
}
