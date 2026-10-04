import "server-only";

import type { EntityType } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { ClientContext } from "@/server/api/services";
import { mapResult, ok, type Result } from "@/server/result";
import { entitiesGateway } from "./gateway";
import {
  entityTypeLabel,
  mentionedClauseView,
  relationToEntity,
  type EntityPageView,
} from "./model/entity-page";
import { resolutionView, type ResolutionView } from "./model/resolution";
import type { EntitiesPort } from "./ports";

type Deps = { fetchImpl?: ClientContext["fetchImpl"]; port?: EntitiesPort };

/** The clauses an entity's page lists, newest document first, at most this many. */
export const CLAUSES_LIMIT = 50;

/** At most this many source versions are read for their names. */
export const SOURCE_VERSION_READS = 50;

function portOf(deps: Deps): EntitiesPort {
  return deps.port ?? entitiesGateway({ fetchImpl: deps.fetchImpl });
}

/** A name resolved the way alignment resolves a mention, as the tool shows it. */
export async function getResolution(
  entityType: EntityType,
  name: string,
  deps: Deps = {},
): Promise<Result<ResolutionView>> {
  return mapResult(await portOf(deps).resolve(entityType, name), resolutionView);
}

/**
 * An entity's page: the entity first (one the rulebook does not hold is the caller's
 * not-found), then the clauses that mention it and the relations to it side by side, then the
 * versions the relations come from, for their names.
 */
export async function getEntityPage(
  entityId: string,
  asOf: string | null,
  deps: Deps = {},
): Promise<Result<EntityPageView>> {
  const port = portOf(deps);
  const entity = await port.entity(entityId);
  if (!entity.ok) return entity;
  const [clauses, relations] = await Promise.all([
    port.clauses(entityId, { limit: CLAUSES_LIMIT, ...(asOf === null ? {} : { asOf }) }),
    port.relationsTo(entityId),
  ]);
  const sources = relations.ok
    ? [...new Set(relations.value.map((relation) => relation.fromRuleVersionId))].slice(
        0,
        SOURCE_VERSION_READS,
      )
    : [];
  const reads = await Promise.all(sources.map((id) => port.version(id)));
  const versions = new Map<string, RuleVersion>();
  reads.forEach((read, index) => {
    if (read.ok) versions.set(sources[index] as string, read.value);
  });
  return ok({
    entity: entity.value,
    typeLabel: entityTypeLabel(entity.value.entityType),
    asOf,
    clauses: clauses.ok
      ? { ok: true, value: clauses.value.map(mentionedClauseView) }
      : { ok: false, error: clauses.error },
    relations: relations.ok
      ? { ok: true, value: relations.value.map((relation) => relationToEntity(relation, versions)) }
      : { ok: false, error: relations.error },
  });
}
