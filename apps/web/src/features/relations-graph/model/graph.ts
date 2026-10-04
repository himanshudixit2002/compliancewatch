import type { RelationKind, RuleRelation } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";

/**
 * The relations around one rule version as a graph: rule versions and entities are the nodes,
 * the rulebook's relations (ADR-017) the edges. The walk from the start version follows every
 * relation from and to each version (and to each entity) up to the chosen depth; each node gets
 * a column, the start in the middle, what it points at to the right and what points at it to the
 * left, which the layout turns into positions for an inline SVG. Nothing is a library: the layout
 * is plain arithmetic, deterministic for the same relations.
 */
export type NodeKind = "version" | "entity";

export interface GraphNode {
  key: string;
  kind: NodeKind;
  /** The walk's column: the start is 0, a target one to the right, a source one to the left. */
  column: number;
  /** "rule_key v2", "Form: example form", or the id when the version could not be read. */
  label: string;
  /** A version's title. */
  detail: string | null;
  status: string | null;
  href: string | null;
  start: boolean;
}

export interface GraphEdge {
  relationId: string;
  from: string;
  to: string;
  relation: RelationKind;
  evidenceClauseRef: string;
  evidenceHref: string;
  periodLabel: string | null;
  newDueOn: string | null;
}

export function versionKey(ruleVersionId: string): string {
  return `version:${ruleVersionId}`;
}

/** An entity end: by its id when aligned, else by its type and the name the relation gives. */
export function entityKey(relation: RuleRelation): string {
  return relation.toEntityId === null
    ? `entity:${relation.toKind}:${relation.toRef}`
    : `entity:${relation.toEntityId}`;
}

/** The node at the other end of a relation read at `node`, with the column it belongs in. */
export function otherEnd(
  relation: RuleRelation,
  at: GraphNode,
): { key: string; kind: NodeKind; column: number; relation: RuleRelation } {
  const fromHere = at.kind === "version" && versionKey(relation.fromRuleVersionId) === at.key;
  if (!fromHere) {
    return {
      key: versionKey(relation.fromRuleVersionId),
      kind: "version",
      column: at.column - 1,
      relation,
    };
  }
  if (relation.toKind === "rule_version" && relation.toRuleVersionId !== null) {
    return {
      key: versionKey(relation.toRuleVersionId),
      kind: "version",
      column: at.column + 1,
      relation,
    };
  }
  return { key: entityKey(relation), kind: "entity", column: at.column + 1, relation };
}

export function versionNode(
  ruleVersionId: string,
  column: number,
  read: RuleVersion | undefined,
  start = false,
): GraphNode {
  return {
    key: versionKey(ruleVersionId),
    kind: "version",
    column,
    label: read === undefined ? ruleVersionId : `${read.ruleKey} v${read.version}`,
    detail: read?.title ?? null,
    status: read?.status ?? null,
    href: hrefFor(screenById("admin.rulebook.version"), { ruleVersionId }),
    start,
  };
}

export function entityNode(relation: RuleRelation, column: number): GraphNode {
  return {
    key: entityKey(relation),
    kind: "entity",
    column,
    label: `${humanise(relation.toKind)}: ${relation.toRef}`,
    detail: null,
    status: null,
    href:
      relation.toEntityId === null
        ? null
        : hrefFor(screenById("admin.rulebook.canonical.entity"), { entityId: relation.toEntityId }),
    start: false,
  };
}

export function graphEdge(relation: RuleRelation, from: string, to: string): GraphEdge {
  return {
    relationId: relation.relationId,
    from,
    to,
    relation: relation.relation,
    evidenceClauseRef: relation.evidenceClauseRef,
    evidenceHref: withQuery(
      hrefFor(screenById("admin.rulebook.document"), { documentId: relation.evidenceDocumentId }),
      { clause_id: relation.evidenceClauseId },
    ),
    periodLabel: relation.periodLabel,
    newDueOn: relation.newDueOn,
  };
}

// ---- Layout ----------------------------------------------------------------------------------

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 56;
export const COLUMN_GAP = 132;
export const ROW_GAP = 32;
export const PADDING = 16;
/** Characters of a label that fit a node; the table gives the whole label. */
export const LABEL_CHARACTERS = 28;

export interface LaidOutNode extends GraphNode {
  x: number;
  y: number;
}

export interface LaidOutEdge extends GraphEdge {
  path: string;
  labelX: number;
  labelY: number;
}

export interface GraphLayout {
  width: number;
  height: number;
  nodes: readonly LaidOutNode[];
  edges: readonly LaidOutEdge[];
}

export function shorten(text: string, characters = LABEL_CHARACTERS): string {
  const points = Array.from(text);
  return points.length <= characters ? text : `${points.slice(0, characters - 1).join("")}…`;
}

function edgePath(from: LaidOutNode, to: LaidOutNode): { path: string; x: number; y: number } {
  const fromY = from.y + NODE_HEIGHT / 2;
  const toY = to.y + NODE_HEIGHT / 2;
  if (to.column > from.column) {
    const x1 = from.x + NODE_WIDTH;
    const x2 = to.x;
    const bend = (x2 - x1) / 2;
    return {
      path: `M ${x1} ${fromY} C ${x1 + bend} ${fromY}, ${x2 - bend} ${toY}, ${x2} ${toY}`,
      x: (x1 + x2) / 2,
      y: (fromY + toY) / 2,
    };
  }
  if (to.column < from.column) {
    const x1 = from.x;
    const x2 = to.x + NODE_WIDTH;
    const bend = (x1 - x2) / 2;
    return {
      path: `M ${x1} ${fromY} C ${x1 - bend} ${fromY}, ${x2 + bend} ${toY}, ${x2} ${toY}`,
      x: (x1 + x2) / 2,
      y: (fromY + toY) / 2,
    };
  }
  // Two nodes of one column: a loop out to the right of the column and back.
  const x = from.x + NODE_WIDTH;
  const out = x + COLUMN_GAP / 2;
  return {
    path: `M ${x} ${fromY} C ${out} ${fromY}, ${out} ${toY}, ${x} ${toY}`,
    x: x + (COLUMN_GAP * 3) / 8,
    y: (fromY + toY) / 2,
  };
}

/**
 * Positions for the nodes and paths for the edges: one column per walk column (shifted so the
 * leftmost is 0), the nodes of a column in label order, the start first in its own.
 */
export function layoutGraph(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): GraphLayout {
  const lowest = Math.min(0, ...nodes.map((node) => node.column));
  const columns = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const column = node.column - lowest;
    columns.set(column, [...(columns.get(column) ?? []), { ...node, column }]);
  }
  const laidOut: LaidOutNode[] = [];
  for (const [column, members] of [...columns.entries()].sort(([a], [b]) => a - b)) {
    const ordered = [...members].sort(
      (a, b) =>
        Number(b.start) - Number(a.start) || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0),
    );
    ordered.forEach((node, row) => {
      laidOut.push({
        ...node,
        x: PADDING + column * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }
  const byKey = new Map(laidOut.map((node) => [node.key, node]));
  const laidEdges = edges.flatMap((edge) => {
    const from = byKey.get(edge.from);
    const to = byKey.get(edge.to);
    if (from === undefined || to === undefined) return [];
    const { path, x, y } = edgePath(from, to);
    return [{ ...edge, path, labelX: x, labelY: y }];
  });
  const columnCount = Math.max(1, columns.size === 0 ? 1 : Math.max(...columns.keys()) + 1);
  const rowCount = Math.max(1, ...[...columns.values()].map((members) => members.length));
  return {
    width: PADDING * 2 + columnCount * NODE_WIDTH + (columnCount - 1) * COLUMN_GAP + COLUMN_GAP / 2,
    height: PADDING * 2 + rowCount * NODE_HEIGHT + (rowCount - 1) * ROW_GAP,
    nodes: laidOut,
    edges: laidEdges,
  };
}

/** The graph a page draws: the start version, the walk's settings, the nodes, edges and layout. */
export interface GraphView {
  start: RuleVersion;
  depth: 1 | 2;
  publishedOnly: boolean;
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  layout: GraphLayout;
  /** The walk met more nodes than the cap and left them out. */
  truncated: boolean;
}
