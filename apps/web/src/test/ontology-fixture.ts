import { ontologyFromDto } from "@/entities/ontology/mappers";
import type { Ontology, OntologyAttributeDto, OntologyDto } from "@/entities/ontology/types";

/**
 * A small `GET /v1/ontology` body for unit tests: one attribute of every type the controls
 * handle, at every level, with synthetic keys, questions and labels ("Example ..."), so no test
 * restates the real ontology's wording. The real body is read from the service by the e2e suite.
 */
function attribute(
  partial: Pick<OntologyAttributeDto, "key" | "type" | "level"> & Partial<OntologyAttributeDto>,
): OntologyAttributeDto {
  return {
    source: "user_input",
    per_financial_year: false,
    definition: `Example definition of ${partial.key}.`,
    question: `Example question about ${partial.key}?`,
    help: "",
    values: [],
    min: null,
    max: null,
    example: null,
    ...partial,
  };
}

export const ONTOLOGY_DTO: OntologyDto = {
  version: "0.0.1",
  wording_version: "0.0.1",
  language: "en",
  review_status: "needs_review",
  operators_by_type: {
    enum: ["eq", "neq", "in", "not_in"],
    ordered_enum: ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte"],
    enum_set: ["contains", "contains_any"],
    boolean: ["eq", "neq"],
    integer: ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte"],
  },
  attributes: [
    attribute({
      key: "example_kind",
      type: "enum",
      level: "registration",
      source: "gstin_lookup",
      help: "Example help line.",
      values: [
        { value: "first", label: "Example first kind" },
        { value: "second", label: "Example second kind" },
      ],
      example: "first",
    }),
    attribute({
      key: "example_since",
      type: "date",
      level: "registration",
      source: "gstin_lookup",
      example: "2000-01-01",
    }),
    attribute({
      key: "state_codes",
      type: "enum_set",
      level: "entity",
      source: "gstin_lookup",
      values: [
        { value: "01", label: "Example place one" },
        { value: "02", label: "Example place two" },
        { value: "03", label: "Example place three" },
      ],
      example: ["01"],
    }),
    attribute({
      key: "example_band",
      type: "ordered_enum",
      level: "entity",
      per_financial_year: true,
      values: [
        { value: "small", label: "Example small band" },
        { value: "medium", label: "Example medium band" },
        { value: "large", label: "Example large band" },
      ],
      example: "medium",
    }),
    attribute({ key: "example_flag", type: "boolean", level: "registration", example: false }),
    attribute({
      key: "example_count",
      type: "integer",
      level: "entity",
      min: 0,
      max: 1000,
      example: 12,
    }),
    attribute({ key: "example_ratio", type: "decimal", level: "location", example: "1.5" }),
    attribute({ key: "example_note", type: "string", level: "location", question: "" }),
    attribute({
      key: "example_derived",
      type: "boolean",
      level: "entity",
      source: "derived",
      question: "",
    }),
  ],
};

/** The fixture as the domain type the screens use. */
export function ontologyFixture(): Ontology {
  return ontologyFromDto(ONTOLOGY_DTO);
}
