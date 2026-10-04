// @vitest-environment node
import { describe, expect, it } from "vitest";
import { relationFromDto } from "@/entities/rulebook/mappers";
import type { RuleRelation } from "@/entities/rulebook/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { err, ok, webError } from "@/server/result";
import { EXAMPLE_ENTITY_ID, relationDto } from "@/test/rulebook-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import type { GraphPort } from "./ports";
import { NODE_CAP, getGraph } from "./queries";

const failure = webError("server", "web-example", "Example failure");

function id(index: number): string {
  return `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

function supersedes(from: number, to: number): RuleRelation {
  return relationFromDto(
    relationDto({
      relation_id: `r-${from}-${to}`,
      from_rule_version_id: id(from),
      relation: "supersedes",
      to_kind: "rule_version",
      to_ref: id(to),
      to_rule_version_id: id(to),
      to_entity_id: null,
    }),
  );
}

/** A port over a fixed set of relations; every version reads, except those named missing. */
function port(relations: RuleRelation[], missing: string[] = []): GraphPort & { asked: string[] } {
  const asked: string[] = [];
  return {
    asked,
    version: async (ruleVersionId) =>
      missing.includes(ruleVersionId)
        ? err(webError("not_found", "web-example", "Gone"))
        : ok(
            ruleVersionFromDto(
              ruleVersionDto({
                rule_version_id: ruleVersionId,
                rule_key: `example_${ruleVersionId.slice(-2)}`,
              }),
            ),
          ),
    relations: async (query) => {
      asked.push(JSON.stringify(query));
      return ok(
        relations.filter(
          (relation) =>
            (query.from !== undefined && relation.fromRuleVersionId === query.from) ||
            (query.to !== undefined && relation.toRuleVersionId === query.to) ||
            (query.toEntity !== undefined && relation.toEntityId === query.toEntity),
        ),
      );
    },
  };
}

describe("getGraph", () => {
  it("draws the start with what it points at and what points at it, one relation out", async () => {
    const graph = await getGraph(
      { ruleVersionId: id(1), depth: 1, publishedOnly: false },
      {
        port: port([
          supersedes(1, 2),
          supersedes(3, 1),
          supersedes(2, 4),
          relationFromDto(relationDto({ from_rule_version_id: id(1) })),
        ]),
      },
    );
    if (!graph.ok) throw new Error("expected the graph");
    expect(graph.value.start.ruleVersionId).toBe(id(1));
    expect(graph.value.nodes.map((node) => [node.key, node.column])).toEqual([
      [`version:${id(1)}`, 0],
      [`version:${id(2)}`, 1],
      [`entity:${EXAMPLE_ENTITY_ID}`, 1],
      [`version:${id(3)}`, -1],
    ]);
    expect(graph.value.nodes.find((node) => node.key === `version:${id(2)}`)?.label).toBe(
      "example_02 v1",
    );
    expect(graph.value.edges.map((edge) => [edge.from, edge.to])).toEqual([
      [`version:${id(1)}`, `version:${id(2)}`],
      [`version:${id(1)}`, `entity:${EXAMPLE_ENTITY_ID}`],
      [`version:${id(3)}`, `version:${id(1)}`],
    ]);
    expect(graph.value.truncated).toBe(false);
    expect(graph.value.layout.nodes).toHaveLength(4);
  });

  it("walks two relations out, through an entity too, with published relations only when asked", async () => {
    const toEntity = relationFromDto(
      relationDto({ relation_id: "e1", from_rule_version_id: id(1) }),
    );
    const alsoToEntity = relationFromDto(
      relationDto({ relation_id: "e2", from_rule_version_id: id(5) }),
    );
    const ports = port([supersedes(1, 2), supersedes(2, 4), toEntity, alsoToEntity], [id(4)]);
    const graph = await getGraph(
      { ruleVersionId: id(1), depth: 2, publishedOnly: true },
      { port: ports },
    );
    if (!graph.ok) throw new Error("expected the graph");
    expect(graph.value.nodes.map((node) => node.key)).toEqual(
      expect.arrayContaining([
        `version:${id(4)}`,
        `version:${id(5)}`,
        `entity:${EXAMPLE_ENTITY_ID}`,
      ]),
    );
    expect(graph.value.nodes.find((node) => node.key === `version:${id(4)}`)?.label).toBe(id(4));
    expect(graph.value.edges).toHaveLength(4);
    expect(ports.asked.every((query) => query.includes('"publishedOnly":true'))).toBe(true);
    expect(ports.asked).toContain(
      JSON.stringify({ toEntity: EXAMPLE_ENTITY_ID, publishedOnly: true }),
    );
  });

  it("does not read relations of an entity that is not aligned", async () => {
    const unaligned = relationFromDto(
      relationDto({ from_rule_version_id: id(1), to_entity_id: null }),
    );
    const ports = port([unaligned]);
    const graph = await getGraph(
      { ruleVersionId: id(1), depth: 2, publishedOnly: false },
      { port: ports },
    );
    expect(graph.ok && graph.value.nodes.map((node) => node.key)).toEqual([
      `version:${id(1)}`,
      "entity:form:example form",
    ]);
    expect(ports.asked.some((query) => query.includes("toEntity"))).toBe(false);
  });

  it("stops at the node cap and says so", async () => {
    const many = Array.from({ length: NODE_CAP + 5 }, (_, index) => supersedes(1, index + 100));
    const graph = await getGraph(
      { ruleVersionId: id(1), depth: 1, publishedOnly: false },
      { port: port(many) },
    );
    expect(graph.ok && graph.value.nodes).toHaveLength(NODE_CAP);
    expect(graph.ok && graph.value.edges).toHaveLength(NODE_CAP - 1);
    expect(graph.ok && graph.value.truncated).toBe(true);
  });

  it("answers the start's failure and a failed relation read", async () => {
    expect(
      await getGraph(
        { ruleVersionId: id(1), depth: 1, publishedOnly: false },
        { port: port([], [id(1)]) },
      ),
    ).toMatchObject({ ok: false, error: { kind: "not_found" } });
    const broken: GraphPort = { ...port([]), relations: async () => err(failure) };
    expect(
      await getGraph({ ruleVersionId: id(1), depth: 1, publishedOnly: false }, { port: broken }),
    ).toEqual(err(failure));
    let calls = 0;
    const halfBroken: GraphPort = {
      ...port([]),
      relations: async () => {
        calls += 1;
        return calls === 2 ? err(failure) : ok([]);
      },
    };
    expect(
      await getGraph(
        { ruleVersionId: id(1), depth: 1, publishedOnly: false },
        { port: halfBroken },
      ),
    ).toEqual(err(failure));
  });
});
