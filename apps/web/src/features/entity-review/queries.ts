import "server-only";

import type { EntityType } from "@/entities/rulebook/types";
import { rulebookWriteAccess, type WriteAccess } from "@/server/api/rulebook-write";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { mapResult, ok, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { entityReviewGateway } from "./gateway";
import { groupView, type GroupView } from "./model/group";
import { QUEUE_PAGE_SIZE, queueView, type QueueFilter, type QueueView } from "./model/queue";
import type { AccessView } from "./ui/decision-shared";

/**
 * The entity review pages' reads: a page of the queue (one more group than a page is asked for,
 * so the view knows whether another page follows), and one group's open mentions with whether the
 * session may decide them (the role, web.admin_rulebook_writes for its tenant, the review token).
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export async function getEntityQueue(
  filter: QueueFilter,
  deps: QueryDeps = {},
): Promise<Result<QueueView>> {
  const groups = await entityReviewGateway(deps).groups({
    entityType: filter.entityType,
    after: filter.after,
    limit: QUEUE_PAGE_SIZE + 1,
  });
  return mapResult(groups, (value) =>
    queueView(hrefFor(screenById("admin.rulebook.entities")), filter, value),
  );
}

/** What a refused write access shows: the refusal's title and detail, which name what to set. */
export function accessView(access: WriteAccess): AccessView {
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
  };
}

export interface GroupPage {
  view: GroupView;
  access: AccessView;
}

export async function getEntityGroup(
  session: ClientPrincipal,
  entityType: EntityType,
  name: string,
  deps: QueryDeps = {},
): Promise<Result<GroupPage>> {
  const [items, access] = await Promise.all([
    entityReviewGateway(deps).items(entityType, name),
    rulebookWriteAccess({ session, fetchImpl: deps.fetchImpl }),
  ]);
  if (!items.ok) return items;
  return ok({ view: groupView(entityType, name, items.value), access: accessView(access) });
}
