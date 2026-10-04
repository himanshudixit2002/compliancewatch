import { describe, expect, it } from "vitest";
import { specificationFromMapping } from "@/entities/rule-version/mappers";
import type { SpecNode } from "@/entities/rule-version/types";
import { ontologyFixture } from "@/test/ontology-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { describeSpecification, operatorWords, valueWords } from "./specification";

function spec(raw: unknown): SpecNode {
  const node = specificationFromMapping(raw);
  if (node === null) throw new Error("expected a condition");
  return node;
}

describe("describeSpecification", () => {
  it("words each predicate with the ontology's labels and meanings", () => {
    const line = describeSpecification(spec(ruleVersionDto().specification), ontologyFixture());
    expect(line).toEqual({
      kind: "group",
      mode: "all_of",
      lead: "All of these hold:",
      items: [
        {
          kind: "predicate",
          attribute: "example_kind",
          definition: "Example definition of example_kind.",
          inOntology: true,
          condition: "is Example first kind",
          judgement: null,
        },
        {
          kind: "predicate",
          attribute: "example_band",
          definition: "Example definition of example_band.",
          inOntology: true,
          condition: "is above Example small band",
          judgement: null,
        },
        {
          kind: "group",
          mode: "not",
          lead: "This does not hold:",
          items: [
            {
              kind: "predicate",
              attribute: "state_codes",
              definition: "Example definition of state_codes.",
              inOntology: true,
              condition: "includes any of Example place one, Example place two",
              judgement: null,
            },
          ],
        },
        {
          kind: "predicate",
          attribute: "example_question",
          definition: null,
          inOntology: false,
          condition: null,
          judgement: "Example condition an analyst judges.",
        },
      ],
    });
  });

  it("shows the values as stored and calls nothing unknown without the ontology", () => {
    const line = describeSpecification(
      spec({ any_of: [{ attribute: "example_kind", operator: "in", value: ["first", "second"] }] }),
      null,
    );
    expect(line).toMatchObject({
      mode: "any_of",
      lead: "At least one of these holds:",
      items: [{ condition: "is one of first, second", inOntology: true, definition: null }],
    });
  });

  it("words a yes or no value and keeps an operator hint beside free text", () => {
    expect(
      describeSpecification(
        spec({ attribute: "example_flag", operator: "eq", value: true, free_text: "Example hint" }),
        ontologyFixture(),
      ),
    ).toMatchObject({ condition: "is Yes", judgement: "Example hint" });
    expect(valueWords(false, undefined)).toBe("No");
    expect(valueWords(12, undefined)).toBe("12");
  });

  it("keeps an unreadable part as its mapping, and an unknown operator as written", () => {
    expect(describeSpecification(spec({ example: 1 }), null)).toEqual({
      kind: "unreadable",
      json: '{"example":1}',
    });
    expect(operatorWords("example_op")).toBe("example_op");
    expect(operatorWords("lte")).toBe("is at most");
  });
});
