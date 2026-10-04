// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  entityFromDto,
  mentionedClauseFromDto,
  relationFromDto,
  resolutionFromDto,
} from "@/entities/rulebook/mappers";
import type { EntityType } from "@/entities/rulebook/types";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { err, ok, webError } from "@/server/result";
import {
  EXAMPLE_ENTITY_ID,
  entityDto,
  mentionedClauseDto,
  relationDto,
} from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import type { EntitiesPort } from "./ports";
import { getEntityPage, getResolution } from "./queries";

const failure = webError("server", "web-example", "Example failure");

function port(overrides: Partial<EntitiesPort> = {}): EntitiesPort & { asked: unknown[] } {
  const asked: unknown[] = [];
  return {
    asked,
    resolve: async (entityType: EntityType, name: string) =>
      ok(
        resolutionFromDto({
          status: "not_found",
          entity_type: entityType,
          name,
          normalised: name.toLowerCase(),
          entity: null,
          candidates: [],
        }),
      ),
    entity: async () => ok(entityFromDto(entityDto())),
    clauses: async (_id, query) => {
      asked.push(query);
      return ok([mentionedClauseFromDto(mentionedClauseDto())]);
    },
    relationsTo: async () =>
      ok([relationFromDto(relationDto()), relationFromDto(relationDto({ relation_id: "r2" }))]),
    version: async () => ok(ruleVersionFromDto(ruleVersionDto())),
    ...overrides,
  };
}

describe("getResolution", () => {
  it("maps the rulebook's answer, or passes its failure on", async () => {
    expect(await getResolution("form", "Example", { port: port() })).toMatchObject({
      ok: true,
      value: { status: "not_found", normalised: "example" },
    });
    expect(
      await getResolution("form", "Example", { port: port({ resolve: async () => err(failure) }) }),
    ).toEqual(err(failure));
  });
});

describe("getEntityPage", () => {
  it("puts the entity, its clauses and the relations to it together, naming each source once", async () => {
    const reads: string[] = [];
    const page = await getEntityPage(EXAMPLE_ENTITY_ID, "2000-06-30", {
      port: port({
        version: async (id) => {
          reads.push(id);
          return ok(ruleVersionFromDto(ruleVersionDto({ rule_version_id: id })));
        },
      }),
    });
    if (!page.ok) throw new Error("expected the page");
    expect(page.value).toMatchObject({
      entity: { canonicalName: "example form" },
      typeLabel: "Form",
      asOf: "2000-06-30",
      clauses: { ok: true, value: [{ mentions: 2 }] },
      relations: { ok: true, value: [{ from: { label: "example_rule v1" } }, {}] },
    });
    expect(reads).toEqual([EXAMPLE_VERSION_ID]);
  });

  it("asks for every document without a date, and keeps each failed part on its own", async () => {
    const parts = port({
      clauses: async () => err(failure),
      relationsTo: async () => err(failure),
    });
    const page = await getEntityPage(EXAMPLE_ENTITY_ID, null, { port: parts });
    expect(page).toMatchObject({
      ok: true,
      value: { asOf: null, clauses: { ok: false }, relations: { ok: false } },
    });
    const plain = port();
    await getEntityPage(EXAMPLE_ENTITY_ID, null, { port: plain });
    expect(plain.asked).toEqual([{ limit: 50 }]);
  });

  it("answers the entity's own failure, and names a source it could not read by its id", async () => {
    const missing = webError("not_found", "web-example", "Gone");
    expect(
      await getEntityPage(EXAMPLE_ENTITY_ID, null, {
        port: port({ entity: async () => err(missing) }),
      }),
    ).toEqual(err(missing));
    const page = await getEntityPage(EXAMPLE_ENTITY_ID, null, {
      port: port({ version: async () => err(failure) }),
    });
    expect(page.ok && page.value.relations).toMatchObject({
      ok: true,
      value: [{ from: { label: null } }, { from: { label: null } }],
    });
  });
});
