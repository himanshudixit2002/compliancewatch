import { attributeOf, optionLabel } from "@/entities/ontology/mappers";
import type { Ontology, OntologyAttribute } from "@/entities/ontology/types";
import type { SpecNode, SpecValue } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * A version's applicability condition in words, for the analyst who checks it against the cited
 * instrument. Each predicate names its attribute by key and gives the ontology's meaning of it;
 * the operator is worded here (chrome, not a regulatory fact) and each value is worded with the
 * ontology's label for it. Nothing is evaluated: this describes what the rule asks.
 */
export type SpecLine =
  | {
      kind: "group";
      /** all_of, any_of or not, with the sentence that opens its items. */
      mode: "all_of" | "any_of" | "not";
      lead: string;
      items: readonly SpecLine[];
    }
  | {
      kind: "predicate";
      attribute: string;
      /** The ontology's meaning of the attribute, or null when the ontology does not hold it. */
      definition: string | null;
      /** False for an attribute the ontology does not hold (a free-text predicate may name one). */
      inOntology: boolean;
      /** "is one of", "is above", ... with the worded values; null for free text alone. */
      condition: string | null;
      /** What an analyst or a model has to judge, when the predicate carries free text. */
      judgement: string | null;
    }
  | { kind: "unreadable"; json: string };

const OPERATOR_KEYS: Readonly<Record<string, MessageKey>> = {
  eq: "ruleVersion.operator.eq",
  neq: "ruleVersion.operator.neq",
  in: "ruleVersion.operator.in",
  not_in: "ruleVersion.operator.not_in",
  gt: "ruleVersion.operator.gt",
  gte: "ruleVersion.operator.gte",
  lt: "ruleVersion.operator.lt",
  lte: "ruleVersion.operator.lte",
  contains: "ruleVersion.operator.contains",
  contains_any: "ruleVersion.operator.contains_any",
};

const LEADS: Readonly<Record<"all_of" | "any_of" | "not", MessageKey>> = {
  all_of: "ruleVersion.spec.allOf",
  any_of: "ruleVersion.spec.anyOf",
  not: "ruleVersion.spec.not",
};

/** The words for an operator; one the app does not know is shown as the kernel writes it. */
export function operatorWords(operator: string): string {
  const key = OPERATOR_KEYS[operator];
  return key === undefined ? operator : t(key);
}

/** A value in the ontology's words: an option's label, Yes or No, or the value as stored. */
export function valueWords(value: SpecValue, attribute: OntologyAttribute | undefined): string {
  if (typeof value === "boolean") {
    return value ? t("ruleVersion.value.yes") : t("ruleVersion.value.no");
  }
  const text = String(value);
  if (attribute !== undefined && attribute.options.length > 0) return optionLabel(attribute, text);
  return text;
}

function predicateLine(
  node: Extract<SpecNode, { kind: "predicate" }>,
  ontology: Ontology | null,
): SpecLine {
  const attribute = ontology === null ? undefined : attributeOf(ontology, node.attribute);
  const values = node.values.map((value) => valueWords(value, attribute)).join(", ");
  return {
    kind: "predicate",
    attribute: node.attribute,
    definition: attribute?.definition ?? null,
    inOntology: ontology === null || attribute !== undefined,
    condition: node.operator === null ? null : `${operatorWords(node.operator)} ${values}`,
    judgement: node.freeText === "" ? null : node.freeText,
  };
}

/**
 * The tree in words. `ontology` is null when it could not be read: the values are then shown as
 * stored, no attribute is called unknown and no meaning is given.
 */
export function describeSpecification(node: SpecNode, ontology: Ontology | null): SpecLine {
  switch (node.kind) {
    case "all_of":
    case "any_of":
      return {
        kind: "group",
        mode: node.kind,
        lead: t(LEADS[node.kind]),
        items: node.items.map((item) => describeSpecification(item, ontology)),
      };
    case "not":
      return {
        kind: "group",
        mode: "not",
        lead: t(LEADS.not),
        items: [describeSpecification(node.item, ontology)],
      };
    case "predicate":
      return predicateLine(node, ontology);
    case "unreadable":
      return { kind: "unreadable", json: JSON.stringify(node.raw) ?? String(node.raw) };
  }
}
