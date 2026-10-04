import { t } from "@/shared/i18n";
import { isHexUuid } from "@/shared/lib/identifiers";

/**
 * The graph's GET form: the version to start from, how many relations away to go (one or two)
 * and whether to draw only relations from published versions. Ids are not personal data, so the
 * choice is in the address and a graph can be shared.
 */
export const GRAPH_PARAMS = {
  version: "rule_version_id",
  depth: "depth",
  scope: "scope",
} as const;

export const DEPTHS = ["1", "2"] as const;
export const SCOPES = ["all", "published"] as const;

export type GraphRead =
  | { kind: "empty" }
  | {
      kind: "invalid";
      values: { version: string; depth: string; scope: string };
      errors: { version: string };
    }
  | { kind: "ok"; ruleVersionId: string; depth: 1 | 2; publishedOnly: boolean };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

export function readGraph(query: Query): GraphRead {
  const version = first(query, GRAPH_PARAMS.version);
  const depth = first(query, GRAPH_PARAMS.depth);
  const scope = first(query, GRAPH_PARAMS.scope);
  if (version === "") return { kind: "empty" };
  if (!isHexUuid(version)) {
    return {
      kind: "invalid",
      values: { version, depth, scope },
      errors: { version: t("graph.form.versionMalformed") },
    };
  }
  return {
    kind: "ok",
    ruleVersionId: version.toLowerCase(),
    depth: depth === "2" ? 2 : 1,
    publishedOnly: scope === "published",
  };
}
