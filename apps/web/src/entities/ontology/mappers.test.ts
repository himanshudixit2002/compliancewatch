import { describe, expect, it } from "vitest";
import { ONTOLOGY_DTO, ontologyFixture } from "@/test/ontology-fixture";
import {
  allowsValue,
  answerableAt,
  attributeOf,
  attributesAt,
  compareByOntologyOrder,
  isAnswerable,
  isAttributeLevel,
  isAttributeSource,
  isAttributeType,
  ontologyFromDto,
  operatorsFor,
  optionLabel,
  questionOf,
} from "./mappers";
import type { OntologyAttribute, OntologyAttributeDto } from "./types";

function attribute(key: string): OntologyAttribute {
  const found = attributeOf(ontologyFixture(), key);
  if (found === undefined) throw new Error(`fixture has no ${key}`);
  return found;
}

describe("ontologyFromDto", () => {
  it("keeps the versions, the review state and every attribute in the service's order", () => {
    const ontology = ontologyFixture();
    expect(ontology.version).toBe("0.0.1");
    expect(ontology.wordingVersion).toBe("0.0.1");
    expect(ontology.language).toBe("en");
    expect(ontology.reviewStatus).toBe("needs_review");
    expect(ontology.wordingReviewed).toBe(false);
    expect(ontology.attributes.map((item) => item.key)).toEqual(
      ONTOLOGY_DTO.attributes.map((item) => item.key),
    );
    expect(ontology.attributes.map((item) => item.order)).toEqual(
      ONTOLOGY_DTO.attributes.map((_, index) => index),
    );
    expect(ontology.unsupported).toEqual([]);
  });

  it("maps the wire names to the domain names and keeps the options in order", () => {
    const band = attribute("example_band");
    expect(band).toMatchObject({
      type: "ordered_enum",
      level: "entity",
      source: "user_input",
      perFinancialYear: true,
      question: "Example question about example_band?",
      min: null,
      max: null,
      example: "medium",
    });
    expect(band.options.map((option) => option.value)).toEqual(["small", "medium", "large"]);
    expect(attribute("example_count")).toMatchObject({ min: 0, max: 1000, example: 12 });
    expect(attribute("example_note").example).toBeNull();
  });

  it("lists attributes of an unknown type, level or source instead of guessing a control", () => {
    const first = ONTOLOGY_DTO.attributes[0] as OntologyAttributeDto;
    const ontology = ontologyFromDto({
      ...ONTOLOGY_DTO,
      review_status: "reviewed",
      attributes: [
        ...ONTOLOGY_DTO.attributes,
        { ...first, key: "odd_type", type: "money" },
        { ...first, key: "odd_level", level: "branch" },
        { ...first, key: "odd_source", source: "partner" },
      ],
    });
    expect(ontology.wordingReviewed).toBe(true);
    expect(ontology.unsupported).toEqual(["odd_type", "odd_level", "odd_source"]);
    expect(attributeOf(ontology, "odd_type")).toBeUndefined();
    expect(ontology.attributes).toHaveLength(ONTOLOGY_DTO.attributes.length);
  });

  it("copies the operators per type", () => {
    const ontology = ontologyFixture();
    expect(operatorsFor(ontology, "boolean")).toEqual(["eq", "neq"]);
    expect(operatorsFor(ontology, "string")).toEqual([]);
  });

  it("recognises the kernel's kinds only", () => {
    expect(isAttributeType("enum_set")).toBe(true);
    expect(isAttributeType("money")).toBe(false);
    expect(isAttributeLevel("location")).toBe(true);
    expect(isAttributeLevel("branch")).toBe(false);
    expect(isAttributeSource("derived")).toBe(true);
    expect(isAttributeSource("partner")).toBe(false);
  });
});

describe("lookups", () => {
  it("finds attributes by key and by level", () => {
    const ontology = ontologyFixture();
    expect(attributeOf(ontology, "missing")).toBeUndefined();
    expect(attributesAt(ontology, "location").map((item) => item.key)).toEqual([
      "example_ratio",
      "example_note",
    ]);
  });

  it("leaves derived attributes out of the answerable ones", () => {
    const ontology = ontologyFixture();
    expect(isAnswerable(attribute("example_derived"))).toBe(false);
    expect(isAnswerable(attribute("example_kind"))).toBe(true);
    expect(answerableAt(ontology, ["entity"]).map((item) => item.key)).toEqual([
      "state_codes",
      "example_band",
      "example_count",
    ]);
  });

  it("labels values from the wording and falls back to the value itself", () => {
    const kind = attribute("example_kind");
    expect(optionLabel(kind, "second")).toBe("Example second kind");
    expect(optionLabel(kind, "third")).toBe("third");
    expect(allowsValue(kind, "first")).toBe(true);
    expect(allowsValue(kind, "third")).toBe(false);
    expect(allowsValue(attribute("example_count"), "anything")).toBe(true);
  });

  it("asks the question, or states the definition when the wording has none", () => {
    expect(questionOf(attribute("example_flag"))).toBe("Example question about example_flag?");
    expect(questionOf(attribute("example_note"))).toBe("Example definition of example_note.");
  });

  it("orders keys by the ontology, unknown keys last by name", () => {
    const keys = ["zeta", "example_count", "alpha", "example_kind"];
    expect([...keys].sort(compareByOntologyOrder(ontologyFixture()))).toEqual([
      "example_kind",
      "example_count",
      "alpha",
      "zeta",
    ]);
  });
});
