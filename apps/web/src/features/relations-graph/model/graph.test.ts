import { describe, expect, it } from "vitest";
import { relationFromDto } from "@/entities/rulebook/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_DOCUMENT_ID, EXAMPLE_ENTITY_ID, relationDto } from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  COLUMN_GAP,
  NODE_HEIGHT,
  NODE_WIDTH,
  PADDING,
  entityKey,
  entityNode,
  graphEdge,
  layoutGraph,
  otherEnd,
  shorten,
  versionKey,
  versionNode,
} from "./graph";

const START = versionNode(EXAMPLE_VERSION_ID, 0, ruleVersionFromDto(ruleVersionDto()), true);
const TO_VERSION = relationFromDto(
  relationDto({
    relation: "supersedes",
    to_kind: "rule_version",
    to_ref: EXAMPLE_OTHER_VERSION_ID,
    to_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
    to_entity_id: null,
  }),
);
const TO_ENTITY = relationFromDto(relationDto());

describe("the graph's nodes and ends", () => {
  it("names a version by rule key and number, or by its id when it was not read", () => {
    expect(START).toMatchObject({
      key: versionKey(EXAMPLE_VERSION_ID),
      label: "example_rule v1",
      detail: "Example rule title",
      status: "draft",
      href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
      start: true,
    });
    expect(versionNode(EXAMPLE_OTHER_VERSION_ID, 1, undefined)).toMatchObject({
      label: EXAMPLE_OTHER_VERSION_ID,
      detail: null,
      status: null,
    });
  });

  it("puts a target to the right, a source to the left, and an entity by its id or name", () => {
    expect(otherEnd(TO_VERSION, START)).toMatchObject({
      key: versionKey(EXAMPLE_OTHER_VERSION_ID),
      kind: "version",
      column: 1,
    });
    expect(otherEnd(TO_ENTITY, START)).toMatchObject({
      key: `entity:${EXAMPLE_ENTITY_ID}`,
      kind: "entity",
      column: 1,
    });
    const other = versionNode(EXAMPLE_OTHER_VERSION_ID, 0, undefined);
    expect(otherEnd(TO_VERSION, other)).toMatchObject({
      key: versionKey(EXAMPLE_VERSION_ID),
      column: -1,
    });
    const unaligned = relationFromDto(relationDto({ to_entity_id: null }));
    expect(entityKey(unaligned)).toBe("entity:form:example form");
    expect(entityNode(unaligned, 1)).toMatchObject({ label: "Form: example form", href: null });
    expect(entityNode(TO_ENTITY, 1).href).toBe(
      `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
    );
  });

  it("links an edge's evidence to its clause in the document", () => {
    expect(graphEdge(TO_ENTITY, START.key, `entity:${EXAMPLE_ENTITY_ID}`).evidenceHref).toContain(
      `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=`,
    );
  });

  it("shortens a long label to what a node holds", () => {
    expect(shorten("Example")).toBe("Example");
    expect(shorten("x".repeat(40))).toBe(`${"x".repeat(27)}…`);
  });
});

describe("layoutGraph", () => {
  const source = versionNode("00000000-0000-4000-8000-0000000000f3", -1, undefined);
  const target = versionNode(EXAMPLE_OTHER_VERSION_ID, 1, undefined);
  const entity = entityNode(TO_ENTITY, 1);
  const nodes = [entity, target, START, source];
  const edges = [
    graphEdge(TO_VERSION, START.key, target.key),
    graphEdge(TO_ENTITY, START.key, entity.key),
    graphEdge(relationFromDto(relationDto({ relation_id: "r3" })), source.key, START.key),
    graphEdge(relationFromDto(relationDto({ relation_id: "r4" })), target.key, entity.key),
    graphEdge(relationFromDto(relationDto({ relation_id: "r5" })), START.key, "version:gone"),
  ];

  it("lays the columns out from the leftmost, each column's nodes in label order", () => {
    const layout = layoutGraph(nodes, edges);
    const at = new Map(layout.nodes.map((node) => [node.key, node]));
    expect(at.get(source.key)).toMatchObject({ column: 0, x: PADDING, y: PADDING });
    expect(at.get(START.key)).toMatchObject({ column: 1, x: PADDING + NODE_WIDTH + COLUMN_GAP });
    // In the third column the version id sorts before "Form: ...".
    expect(at.get(target.key)?.y).toBe(PADDING);
    expect(at.get(entity.key)?.y).toBe(PADDING + NODE_HEIGHT + 32);
    expect(layout.width).toBe(PADDING * 2 + 3 * NODE_WIDTH + 2 * COLUMN_GAP + COLUMN_GAP / 2);
    expect(layout.height).toBe(PADDING * 2 + 2 * NODE_HEIGHT + 32);
  });

  it("draws an edge to the right, to the left and within a column, and drops one to a missing node", () => {
    const layout = layoutGraph(nodes, edges);
    expect(layout.edges).toHaveLength(4);
    for (const edge of layout.edges) expect(edge.path).toMatch(/^M [\d.]+ [\d.]+ C /);
    const within = layout.edges.find((edge) => edge.relationId === "r4");
    expect(within?.labelX).toBeGreaterThan(within?.path.length ?? 0);
  });

  it("draws a lone start node", () => {
    const layout = layoutGraph([START], []);
    expect(layout.nodes).toHaveLength(1);
    expect(layout.edges).toHaveLength(0);
    expect(layout.width).toBe(PADDING * 2 + NODE_WIDTH + COLUMN_GAP / 2);
  });
});
