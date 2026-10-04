import { livePageHref } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import type { ListCount } from "../ports";

/**
 * The count tiles at the top of the admin home: what each counts, which tool lists those
 * records, and how a count or a failed read is shown. A tile links to its tool once that tool is
 * built (a live page in the registry); until then it says the tool is not built yet. A failed
 * read shows that tile's error, with the correlation id, and the other tiles still render.
 */
export type CountTileKey = "entityGroups" | "relationCandidates" | "rules" | "prompts";

export interface CountTileDefinition {
  key: CountTileKey;
  /** The static route of the tool that lists these records. */
  toolRoute: string;
}

export const COUNT_TILES: readonly CountTileDefinition[] = [
  { key: "entityGroups", toolRoute: "/admin/rulebook/entities" },
  { key: "relationCandidates", toolRoute: "/admin/rulebook/relations" },
  { key: "rules", toolRoute: "/admin/rulebook/rules" },
  { key: "prompts", toolRoute: "/admin/llm/prompts" },
];

export interface CountTileView {
  key: CountTileKey;
  title: string;
  /** "12", or "200+" when the page read was full; null when the read failed. */
  value: string | null;
  /** A second line, such as the open mentions behind the entity groups. */
  detail: string | null;
  /** The tool that lists these records, once it is built. */
  href: string | null;
  error: ServiceErrorLike | null;
}

/** What a tile's read produced: a count or the error to show in its place. */
export type CountOutcome = { ok: true; value: ListCount } | { ok: false; error: ServiceErrorLike };

const TITLES: Readonly<Record<CountTileKey, () => string>> = {
  entityGroups: () => t("admin.tile.entityGroups"),
  relationCandidates: () => t("admin.tile.relationCandidates"),
  rules: () => t("admin.tile.rules"),
  prompts: () => t("admin.tile.prompts"),
};

/** "12", or "200+" for a full page. */
export function countLabel(count: ListCount): string {
  return count.capped ? t("admin.tile.atLeast", { count: count.count }) : String(count.count);
}

function detailOf(key: CountTileKey, count: ListCount): string | null {
  if (key !== "entityGroups" || count.within === undefined) return null;
  return t("admin.tile.openMentions", { count: count.within });
}

/** Keeps what ServiceError shows and drops the rest of the error, so the view gets plain data. */
export function toServiceErrorLike(error: ServiceErrorLike): ServiceErrorLike {
  const detail = error.problem?.detail ?? undefined;
  return {
    message: error.message,
    requestId: error.requestId,
    ...(error.status === undefined ? {} : { status: error.status }),
    ...(detail === undefined ? {} : { problem: { detail } }),
  };
}

export function toCountTile(
  definition: CountTileDefinition,
  outcome: CountOutcome,
  hrefOf: (route: string) => string | null = livePageHref,
): CountTileView {
  const base = {
    key: definition.key,
    title: TITLES[definition.key](),
    href: hrefOf(definition.toolRoute),
  };
  if (!outcome.ok) {
    return { ...base, value: null, detail: null, error: toServiceErrorLike(outcome.error) };
  }
  return {
    ...base,
    value: countLabel(outcome.value),
    detail: detailOf(definition.key, outcome.value),
    error: null,
  };
}
