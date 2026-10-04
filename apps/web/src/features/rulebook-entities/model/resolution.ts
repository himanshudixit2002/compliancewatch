import type { Tone } from "@compliancewatch/ui";
import type {
  CanonicalEntity,
  EntityResolution,
  ResolutionStatus,
} from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { entityTypeLabel } from "./entity-type";

/**
 * A resolution as the tool shows it: the status in words with what it means (the rulebook's own
 * definitions: resolved, ambiguous, not_found, unqualified, empty), the name after the kernel's
 * normalisation, and the entities it points at, each to open.
 */
const STATUSES: Readonly<
  Record<ResolutionStatus, { label: MessageKey; meaning: MessageKey; tone: Tone }>
> = {
  resolved: {
    label: "entities.status.resolved",
    meaning: "entities.meaning.resolved",
    tone: "success",
  },
  ambiguous: {
    label: "entities.status.ambiguous",
    meaning: "entities.meaning.ambiguous",
    tone: "warning",
  },
  not_found: {
    label: "entities.status.not_found",
    meaning: "entities.meaning.not_found",
    tone: "neutral",
  },
  unqualified: {
    label: "entities.status.unqualified",
    meaning: "entities.meaning.unqualified",
    tone: "warning",
  },
  empty: { label: "entities.status.empty", meaning: "entities.meaning.empty", tone: "neutral" },
};

export interface EntityChoice {
  entityId: string;
  href: string;
  name: string;
  typeLabel: string;
  aliases: readonly string[];
}

export interface ResolutionView {
  status: ResolutionStatus;
  statusLabel: string;
  meaning: string;
  tone: Tone;
  typeLabel: string;
  name: string;
  normalised: string;
  /** The entity (resolved) or the candidates sharing the alias (ambiguous); empty otherwise. */
  choices: readonly EntityChoice[];
}

export function entityPageHref(entityId: string): string {
  return hrefFor(screenById("admin.rulebook.canonical.entity"), { entityId });
}

export function entityChoice(entity: CanonicalEntity): EntityChoice {
  return {
    entityId: entity.entityId,
    href: entityPageHref(entity.entityId),
    name: entity.canonicalName,
    typeLabel: entityTypeLabel(entity.entityType),
    aliases: entity.aliases,
  };
}

export function resolutionView(resolution: EntityResolution): ResolutionView {
  const status = STATUSES[resolution.status];
  const entities =
    resolution.entity === null
      ? resolution.candidates
      : [resolution.entity, ...resolution.candidates];
  return {
    status: resolution.status,
    statusLabel: t(status.label),
    meaning: t(status.meaning),
    tone: status.tone,
    typeLabel: entityTypeLabel(resolution.entityType),
    name: resolution.name,
    normalised: resolution.normalised,
    choices: entities
      .filter(
        (entity, index) =>
          entities.findIndex((other) => other.entityId === entity.entityId) === index,
      )
      .map(entityChoice),
  };
}
