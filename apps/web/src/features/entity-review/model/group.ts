import type { EntityGroupDecided, EntityType, ReviewItem } from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";
import type { DecisionResult, ItemRow } from "../ui/decision-shared";
import { documentMarkHref, reviewReasonLabel } from "./labels";
import { entityTypeLabel, groupNameLabel, isEntityType } from "./queue";

/**
 * One review group: its open mentions, each linking to the place it was found, and what a
 * decision over the group recorded. The group is named in the query (`?type=&name=`): a proposed
 * name may hold a slash ("01/2000-example"), which a path segment cannot carry reliably, and an
 * empty name is a group too, so `name=` is a value and only a missing type means no group.
 */
export const GROUP_PARAMS = { type: "type", name: "name" } as const;

/** The rulebook takes a proposed name of up to 400 characters. */
export const NAME_MAX_LENGTH = 400;

export type GroupRead =
  | { kind: "none" }
  | { kind: "invalid"; message: string }
  | { kind: "ok"; entityType: EntityType; name: string };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string | undefined {
  const value = query[key];
  return Array.isArray(value) ? value[0] : value;
}

export function readGroup(query: Query): GroupRead {
  const type = first(query, GROUP_PARAMS.type);
  const name = first(query, GROUP_PARAMS.name) ?? "";
  if (type === undefined || type.trim() === "") {
    return name === ""
      ? { kind: "none" }
      : { kind: "invalid", message: t("entityReview.group.typeMissing") };
  }
  if (!isEntityType(type.trim())) {
    return { kind: "invalid", message: t("entityReview.group.typeUnknown", { type: type.trim() }) };
  }
  if (name.length > NAME_MAX_LENGTH) {
    return {
      kind: "invalid",
      message: t("entityReview.group.nameTooLong", { max: NAME_MAX_LENGTH }),
    };
  }
  return { kind: "ok", entityType: type.trim() as EntityType, name };
}

/** The open mentions in the order the rulebook lists them. */
export function itemRows(items: readonly ReviewItem[]): ItemRow[] {
  return items.map((item) => ({
    reviewId: item.reviewId,
    text: item.mentionText,
    reasonLabel: reviewReasonLabel(item.reason),
    documentId: item.documentId,
    documentHref: documentMarkHref(item),
  }));
}

/** The types whose names need their statute after "@" to name one provision (36(4)@example-act). */
const PROVISIONS: readonly EntityType[] = ["section", "rule"];

/**
 * Whether the proposed name can be an entity's name, as the rulebook decides it: not empty, and a
 * section or a rule only with its statute. Such a group cannot make an entity, and a decision
 * over it names its mentions (the rulebook refuses one that does not).
 */
export function canName(entityType: EntityType, name: string): boolean {
  return name !== "" && (!PROVISIONS.includes(entityType) || name.includes("@"));
}

export interface GroupView {
  entityType: EntityType;
  typeLabel: string;
  name: string;
  nameLabel: string;
  items: ItemRow[];
  /** The canonical entities tool, asked how this name resolves today; null for an empty name. */
  resolveHref: string | null;
  /** Back to the queue, listing this group's type. */
  queueHref: string;
  /** False for an empty name or a provision without its statute (see canName). */
  nameable: boolean;
}

export function groupView(
  entityType: EntityType,
  name: string,
  items: readonly ReviewItem[],
): GroupView {
  return {
    entityType,
    typeLabel: entityTypeLabel(entityType),
    name,
    nameLabel: groupNameLabel(name),
    items: itemRows(items),
    resolveHref:
      name === ""
        ? null
        : withQuery(hrefFor(screenById("admin.rulebook.canonical")), { type: entityType, name }),
    queueHref: withQuery(hrefFor(screenById("admin.rulebook.entities")), { type: entityType }),
    nameable: canName(entityType, name),
  };
}

const RESOLUTIONS: Readonly<Record<string, MessageKey>> = {
  created: "entityReview.resolution.created",
  aliased: "entityReview.resolution.aliased",
  matched: "entityReview.resolution.matched",
};

export function decisionResult(decided: EntityGroupDecided): DecisionResult {
  const resolutionKey = decided.resolution === null ? undefined : RESOLUTIONS[decided.resolution];
  return {
    kind: "decided",
    message: t("entityReview.done", { count: decided.itemsClosed }),
    statusLabel: humanise(decided.status),
    resolutionLabel:
      decided.resolution === null
        ? null
        : resolutionKey === undefined
          ? humanise(decided.resolution)
          : t(resolutionKey),
    entityId: decided.entityId,
    entityHref:
      decided.entityId === null
        ? null
        : hrefFor(screenById("admin.rulebook.canonical.entity"), { entityId: decided.entityId }),
    itemsClosed: decided.itemsClosed,
    relationTargetsUpdated: decided.relationTargetsUpdated,
  };
}

/**
 * A decision the rulebook refused because its mentions had been decided before it arrived: the
 * whole group's, or the ones included. The group read lists open mentions only, so who decided
 * them is not known here and not claimed.
 */
export function alreadyDecidedResult(included: boolean): DecisionResult {
  return {
    kind: "already",
    message: included ? t("entityReview.already.included") : t("entityReview.already.group"),
  };
}
