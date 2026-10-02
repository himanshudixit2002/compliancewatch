import {
  ATTRIBUTE_LEVELS,
  ATTRIBUTE_SOURCES,
  ATTRIBUTE_TYPES,
  WORDING_NEEDS_REVIEW,
  type AttributeLevel,
  type AttributeSource,
  type AttributeType,
  type Ontology,
  type OntologyAttribute,
  type OntologyAttributeDto,
  type OntologyDto,
  type OntologyOption,
} from "./types";

function isOneOf<T extends string>(values: readonly T[], value: string): value is T {
  return (values as readonly string[]).includes(value);
}

export function isAttributeType(value: string): value is AttributeType {
  return isOneOf(ATTRIBUTE_TYPES, value);
}

export function isAttributeLevel(value: string): value is AttributeLevel {
  return isOneOf(ATTRIBUTE_LEVELS, value);
}

export function isAttributeSource(value: string): value is AttributeSource {
  return isOneOf(ATTRIBUTE_SOURCES, value);
}

function bound(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function attributeFromDto(dto: OntologyAttributeDto, order: number): OntologyAttribute | null {
  const { type, level, source } = dto;
  if (!isAttributeType(type) || !isAttributeLevel(level) || !isAttributeSource(source)) {
    return null;
  }
  return {
    key: dto.key,
    type,
    level,
    source,
    perFinancialYear: dto.per_financial_year,
    definition: dto.definition,
    question: dto.question,
    help: dto.help,
    options: dto.values.map((option) => ({ value: option.value, label: option.label })),
    min: bound(dto.min),
    max: bound(dto.max),
    example: dto.example ?? null,
    order,
  };
}

/** The domain ontology from the wire body, attributes in the service's order. */
export function ontologyFromDto(dto: OntologyDto): Ontology {
  const attributes: OntologyAttribute[] = [];
  const unsupported: string[] = [];
  dto.attributes.forEach((item) => {
    const attribute = attributeFromDto(item, attributes.length);
    if (attribute === null) unsupported.push(item.key);
    else attributes.push(attribute);
  });
  const operatorsByType: Record<string, readonly string[]> = {};
  for (const [type, operators] of Object.entries(dto.operators_by_type)) {
    operatorsByType[type] = [...operators];
  }
  return {
    version: dto.version,
    wordingVersion: dto.wording_version,
    language: dto.language,
    reviewStatus: dto.review_status,
    wordingReviewed: dto.review_status !== WORDING_NEEDS_REVIEW,
    operatorsByType,
    attributes,
    unsupported,
  };
}

/** The attribute with this key, or undefined when the ontology has none. */
export function attributeOf(ontology: Ontology, key: string): OntologyAttribute | undefined {
  return ontology.attributes.find((attribute) => attribute.key === key);
}

/** The attributes held at one level of the hierarchy, in ontology order. */
export function attributesAt(ontology: Ontology, level: AttributeLevel): OntologyAttribute[] {
  return ontology.attributes.filter((attribute) => attribute.level === level);
}

/** An attribute a person answers or confirms: pre-filled or asked, never derived. */
export function isAnswerable(attribute: OntologyAttribute): boolean {
  return attribute.source !== "derived";
}

/** The answerable attributes at the given levels, in ontology order. */
export function answerableAt(
  ontology: Ontology,
  levels: readonly AttributeLevel[],
): OntologyAttribute[] {
  return ontology.attributes.filter(
    (attribute) => isAnswerable(attribute) && levels.includes(attribute.level),
  );
}

/** The option with this value, or undefined. */
export function optionOf(attribute: OntologyAttribute, value: string): OntologyOption | undefined {
  return attribute.options.find((option) => option.value === value);
}

/** The wording's label for a value; the value itself when the wording has none. */
export function optionLabel(attribute: OntologyAttribute, value: string): string {
  return optionOf(attribute, value)?.label ?? value;
}

/** True when the value is one the attribute allows (always true for a type without options). */
export function allowsValue(attribute: OntologyAttribute, value: string): boolean {
  return attribute.options.length === 0 || optionOf(attribute, value) !== undefined;
}

/** The onboarding question, or the definition for an attribute the wording asks nothing about. */
export function questionOf(attribute: OntologyAttribute): string {
  return attribute.question.trim() === "" ? attribute.definition : attribute.question;
}

/** The operators a rule predicate may use on the attribute's type, in the service's order. */
export function operatorsFor(ontology: Ontology, type: AttributeType): readonly string[] {
  return ontology.operatorsByType[type] ?? [];
}

/** Orders keys by their position in the ontology; keys it does not hold go last, by name. */
export function compareByOntologyOrder(ontology: Ontology): (a: string, b: string) => number {
  const position = new Map(
    ontology.attributes.map((attribute) => [attribute.key, attribute.order]),
  );
  return (a, b) => {
    const left = position.get(a) ?? Number.MAX_SAFE_INTEGER;
    const right = position.get(b) ?? Number.MAX_SAFE_INTEGER;
    return left - right || a.localeCompare(b);
  };
}
