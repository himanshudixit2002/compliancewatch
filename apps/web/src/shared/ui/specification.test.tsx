import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { specificationFromMapping } from "@/entities/rule-version/mappers";
import type { SpecNode } from "@/entities/rule-version/types";
import { ontologyFixture } from "@/test/ontology-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import {
  SpecificationView,
  describeSpecification,
  operatorWords,
  specificationText,
  valueWords,
} from "./specification";

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

describe("specificationText", () => {
  it("reads the words as lines, two spaces deeper per level, as the rulebook describes them", () => {
    const line = describeSpecification(spec(ruleVersionDto().specification), ontologyFixture());
    expect(specificationText(line)).toEqual([
      "All of these hold:",
      "  example_kind is Example first kind",
      "  example_band is above Example small band",
      "  This does not hold:",
      "    state_codes includes any of Example place one, Example place two",
      "  example_question",
      "    Needs judgement: Example condition an analyst judges.",
    ]);
    expect(specificationText(describeSpecification(spec({ example: 1 }), null))).toEqual([
      'A part of the condition this page cannot read, as stored: {"example":1}',
    ]);
  });
});

describe("SpecificationView", () => {
  it("shows each predicate with its meaning, and says what an empty group holds for", async () => {
    const line = describeSpecification(spec(ruleVersionDto().specification), ontologyFixture());
    const { container } = render(<SpecificationView line={line} />);
    expect(screen.getByText("All of these hold:")).toBeDefined();
    expect(screen.getByText("Needs judgement: Example condition an analyst judges.")).toBeDefined();
    expect(screen.getByText("Not in the ontology")).toBeDefined();
    expect(container.querySelectorAll("[data-slot='spec-predicate']")).toHaveLength(4);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says an empty all of holds for every business and an empty any of for none", () => {
    const { rerender } = render(
      <SpecificationView line={describeSpecification(spec({ all_of: [] }), null)} />,
    );
    expect(
      screen.getByText("Nothing is listed here, so this group holds for every business."),
    ).toBeDefined();
    rerender(<SpecificationView line={describeSpecification(spec({ any_of: [] }), null)} />);
    expect(
      screen.getByText("Nothing is listed here, so this group holds for no business."),
    ).toBeDefined();
  });
});
