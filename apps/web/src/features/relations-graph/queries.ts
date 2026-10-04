import "server-only";

import type { RuleRelation } from "@/entities/rulebook/types";
import type { ClientContext } from "@/server/api/services";
import { err, ok, type ApiError, type Result } from "@/server/result";
import { graphGateway } from "./gateway";
import {
  entityNode,
  graphEdge,
  layoutGraph,
  otherEnd,
  versionKey,
  versionNode,
  type GraphNode,
  type GraphView,
} from "./model/graph";
import type { GraphPort } from "./ports";

type Deps = { fetchImpl?: ClientContext["fetchImpl"]; port?: GraphPort };

/** The most nodes a graph draws; past it the walk stops and the page says so. */
export const NODE_CAP = 40;

function idOf(key: string): string {
  return key.slice(key.indexOf(":") + 1);
}

async function relationsAt(
  port: GraphPort,
  node: GraphNode,
  publishedOnly: boolean,
): Promise<Result<RuleRelation[]>> {
  if (node.kind === "entity") {
    // An entity named by a relation but not aligned has no id to read relations by.
    if (node.key.split(":").length > 2) return ok([]);
    const toEntity = await port.relations({ toEntity: idOf(node.key), publishedOnly });
    return toEntity.ok ? ok([...toEntity.value]) : toEntity;
  }
  const id = idOf(node.key);
  const [from, to] = await Promise.all([
    port.relations({ from: id, publishedOnly }),
    port.relations({ to: id, publishedOnly }),
  ]);
  if (!from.ok) return from;
  if (!to.ok) return to;
  return ok([...from.value, ...to.value]);
}

/**
 * The relations around a rule version: the version first (one the rulebook does not hold is the
 * caller's to report on the form), then a walk of `depth` relations out from it, then each other
 * version read for its name. A failed relation read fails the graph, since a graph missing some
 * relations would mislead; a version that cannot be read is drawn by its id.
 */
export async function getGraph(
  read: { ruleVersionId: string; depth: 1 | 2; publishedOnly: boolean },
  deps: Deps = {},
): Promise<Result<GraphView, ApiError>> {
  const port = deps.port ?? graphGateway({ fetchImpl: deps.fetchImpl });
  const start = await port.version(read.ruleVersionId);
  if (!start.ok) return start;
  const nodes = new Map<string, GraphNode>([
    [versionKey(read.ruleVersionId), versionNode(read.ruleVersionId, 0, start.value, true)],
  ]);
  const relations = new Map<string, { relation: RuleRelation; from: string; to: string }>();
  let frontier: GraphNode[] = [...nodes.values()];
  let truncated = false;
  for (let level = 0; level < read.depth; level += 1) {
    const next: GraphNode[] = [];
    const reads = await Promise.all(
      frontier.map((node) => relationsAt(port, node, read.publishedOnly)),
    );
    for (const [index, result] of reads.entries()) {
      if (!result.ok) return err(result.error);
      const at = frontier[index] as GraphNode;
      for (const relation of result.value) {
        const end = otherEnd(relation, at);
        if (!nodes.has(end.key)) {
          if (nodes.size >= NODE_CAP) {
            truncated = true;
            continue;
          }
          const node =
            end.kind === "version"
              ? versionNode(idOf(end.key), end.column, undefined)
              : entityNode(relation, end.column);
          nodes.set(end.key, node);
          next.push(node);
        }
        const fromKey = versionKey(relation.fromRuleVersionId);
        const toKey =
          relation.toKind === "rule_version" && relation.toRuleVersionId !== null
            ? versionKey(relation.toRuleVersionId)
            : end.kind === "entity"
              ? end.key
              : at.key;
        relations.set(relation.relationId, { relation, from: fromKey, to: toKey });
      }
    }
    frontier = next;
  }
  const others = [...nodes.values()].filter((node) => node.kind === "version" && !node.start);
  const versions = await Promise.all(others.map((node) => port.version(idOf(node.key))));
  versions.forEach((version, index) => {
    const node = others[index] as GraphNode;
    if (version.ok) nodes.set(node.key, versionNode(idOf(node.key), node.column, version.value));
  });
  const nodeList = [...nodes.values()];
  const edges = [...relations.values()]
    .filter(({ from, to }) => nodes.has(from) && nodes.has(to))
    .map(({ relation, from, to }) => graphEdge(relation, from, to));
  return ok({
    start: start.value,
    depth: read.depth,
    publishedOnly: read.publishedOnly,
    nodes: nodeList,
    edges,
    layout: layoutGraph(nodeList, edges),
    truncated,
  });
}
