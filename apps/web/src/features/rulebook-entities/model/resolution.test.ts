import { describe, expect, it } from "vitest";
import { entityFromDto, resolutionFromDto } from "@/entities/rulebook/mappers";
import { EXAMPLE_ENTITY_ID, EXAMPLE_OTHER_ENTITY_ID, entityDto } from "@/test/rulebook-fixture";
import { entityChoice, resolutionView } from "./resolution";

describe("resolutionView", () => {
  it("names a resolved entity, to open", () => {
    const view = resolutionView(
      resolutionFromDto({
        status: "resolved",
        entity_type: "form",
        name: "Example Form",
        normalised: "example form",
        entity: entityDto(),
        candidates: [],
      }),
    );
    expect(view).toEqual({
      status: "resolved",
      statusLabel: "Resolved",
      meaning: "The name is the canonical name or an alias of one entity.",
      tone: "success",
      typeLabel: "Form",
      name: "Example Form",
      normalised: "example form",
      choices: [
        {
          entityId: EXAMPLE_ENTITY_ID,
          href: `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
          name: "example form",
          typeLabel: "Form",
          aliases: ["example form 1", "form e"],
        },
      ],
    });
  });

  it("offers every candidate of an ambiguous alias once", () => {
    const view = resolutionView(
      resolutionFromDto({
        status: "ambiguous",
        entity_type: "form",
        name: "Example",
        normalised: "example",
        entity: null,
        candidates: [
          entityDto(),
          entityDto({ entity_id: EXAMPLE_OTHER_ENTITY_ID, canonical_name: "example form two" }),
          entityDto(),
        ],
      }),
    );
    expect(view.tone).toBe("warning");
    expect(view.choices.map((choice) => choice.entityId)).toEqual([
      EXAMPLE_ENTITY_ID,
      EXAMPLE_OTHER_ENTITY_ID,
    ]);
  });

  it("says what each status without an entity means", () => {
    for (const [status, meaning] of [
      ["not_found", /No entity has this name/],
      ["unqualified", /without its statute/],
      ["empty", /Nothing is left of the name/],
    ] as const) {
      const view = resolutionView(
        resolutionFromDto({
          status,
          entity_type: "section",
          name: "Example",
          normalised: "",
          entity: null,
          candidates: [],
        }),
      );
      expect(view.meaning).toMatch(meaning);
      expect(view.choices).toEqual([]);
    }
    expect(entityChoice(entityFromDto(entityDto({ aliases: [] }))).aliases).toEqual([]);
  });
});
