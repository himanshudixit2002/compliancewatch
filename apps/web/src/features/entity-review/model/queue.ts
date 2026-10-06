import { ENTITY_TYPES, type EntityType, type MentionGroup } from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";
import { documentMarkHref, reviewReasonLabel } from "./labels";

/**
 * The entity review queue: the open mentions alignment could not settle, one row per (entity
 * type, proposed name) group, in the rulebook's order (by type, then name), a page at a time.
 * The query string names the type to list and where the page starts (the last group of the page
 * before), so a page can be shared; entity names are regulatory references, not personal data.
 *
 *   type        one entity type, or every type when absent
 *   after_type  with after_name: continue after this group
 *   after_name  (a group's name may be empty, so after_type alone starts after the empty name)
 */
export const QUEUE_PARAMS = {
  type: "type",
  afterType: "after_type",
  afterName: "after_name",
} as const;

/** Rows a page shows; the gateway asks for one more to know whether another page follows. */
export const QUEUE_PAGE_SIZE = 25;

export interface GroupKey {
  entityType: EntityType;
  name: string;
}

export interface QueueFilter {
  entityType: EntityType | null;
  after: GroupKey | null;
}

export type QueueRead =
  | { kind: "ok"; filter: QueueFilter }
  /** The type is not one the rulebook knows: nothing is read, and the field says why. */
  | { kind: "invalid"; value: string; filter: QueueFilter };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string | undefined {
  const value = query[key];
  return Array.isArray(value) ? value[0] : value;
}

export function isEntityType(value: string): value is EntityType {
  return (ENTITY_TYPES as readonly string[]).includes(value);
}

/** The filter from the query; a cursor that is not a group's key is dropped (the first page). */
export function readQueue(query: Query): QueueRead {
  const type = (first(query, QUEUE_PARAMS.type) ?? "").trim();
  const afterType = (first(query, QUEUE_PARAMS.afterType) ?? "").trim();
  const afterName = first(query, QUEUE_PARAMS.afterName) ?? "";
  const after = isEntityType(afterType) ? { entityType: afterType, name: afterName } : null;
  if (type === "") return { kind: "ok", filter: { entityType: null, after } };
  if (!isEntityType(type)) {
    return { kind: "invalid", value: type, filter: { entityType: null, after: null } };
  }
  return { kind: "ok", filter: { entityType: type, after } };
}

/** A path with its query; unlike withQuery, an empty value stays (a group's name may be ""). */
function hrefWith(pathname: string, entries: readonly (readonly [string, string])[]): string {
  const text = new URLSearchParams(entries.map(([key, value]) => [key, value])).toString();
  return text === "" ? pathname : `${pathname}?${text}`;
}

/** The queue's address for a filter, from its page path. */
export function queueHref(pathname: string, filter: QueueFilter): string {
  const entries: [string, string][] = [];
  if (filter.entityType !== null) entries.push([QUEUE_PARAMS.type, filter.entityType]);
  if (filter.after !== null) {
    entries.push([QUEUE_PARAMS.afterType, filter.after.entityType]);
    entries.push([QUEUE_PARAMS.afterName, filter.after.name]);
  }
  return hrefWith(pathname, entries);
}

/** One group's page: `?type=&name=` (a name may hold a slash, so it is never a path segment). */
export function groupHref(entityType: EntityType, name: string): string {
  return hrefWith(hrefFor(screenById("admin.rulebook.entities.group")), [
    ["type", entityType],
    ["name", name],
  ]);
}

/** An entity type as people read it: "hsn_code" is "HSN code". */
export function entityTypeLabel(entityType: string): string {
  return humanise(entityType);
}

/** The group's name as shown: the proposed name, or a note that the mention named nothing. */
export function groupNameLabel(name: string): string {
  return name === "" ? t("entityReview.emptyName") : name;
}

export interface QueueRow {
  key: string;
  entityType: EntityType;
  typeLabel: string;
  name: string;
  nameLabel: string;
  openCount: number;
  href: string;
  /** The first open mention, with why it is open and a link marking it in its document. */
  example: { text: string; reasonLabel: string; documentHref: string } | null;
}

export function queueRow(group: MentionGroup): QueueRow {
  const example = group.examples[0];
  return {
    key: `${group.entityType} ${group.proposedName}`,
    entityType: group.entityType,
    typeLabel: entityTypeLabel(group.entityType),
    name: group.proposedName,
    nameLabel: groupNameLabel(group.proposedName),
    openCount: group.openCount,
    href: groupHref(group.entityType, group.proposedName),
    example:
      example === undefined
        ? null
        : {
            text: example.mentionText,
            reasonLabel: reviewReasonLabel(example.reason),
            documentHref: documentMarkHref(example),
          },
  };
}

export interface QueueView {
  filter: QueueFilter;
  rows: QueueRow[];
  /** How many open mentions the groups on this page hold. */
  mentionsOnPage: number;
  nextHref: string | null;
  firstHref: string | null;
}

/**
 * The page from the groups the rulebook returned (up to one more than a page): the rows, and the
 * next page after the last row shown when another group followed it.
 */
export function queueView(
  pathname: string,
  filter: QueueFilter,
  groups: readonly MentionGroup[],
): QueueView {
  const shown = groups.slice(0, QUEUE_PAGE_SIZE);
  const last = shown.at(-1);
  const more = groups.length > QUEUE_PAGE_SIZE && last !== undefined;
  return {
    filter,
    rows: shown.map(queueRow),
    mentionsOnPage: shown.reduce((sum, group) => sum + group.openCount, 0),
    nextHref: more
      ? queueHref(pathname, {
          entityType: filter.entityType,
          after: { entityType: last.entityType, name: last.proposedName },
        })
      : null,
    firstHref:
      filter.after === null
        ? null
        : queueHref(pathname, { entityType: filter.entityType, after: null }),
  };
}

/** The type filter's options: every type, then the kernel's ten in its order. */
export function typeOptions(): { value: string; label: string }[] {
  return [
    { value: "", label: t("entityReview.everyType") },
    ...ENTITY_TYPES.map((value) => ({ value, label: entityTypeLabel(value) })),
  ];
}
