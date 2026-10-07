import { Badge } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * A rule version's applicability condition in words, for the analyst who checks it against the
 * cited instrument: the rule version page shows a version's condition, and the review workbench
 * shows a draft's and previews the predicate editor's as it is built. Each predicate names its
 * attribute by key and gives the ontology's meaning of it; the operator is worded here (chrome,
 * not a regulatory fact) and each value is worded with the ontology's label for it. Nothing is
 * evaluated: this describes what the rule asks.
 *
 * The tree and the ontology are taken structurally, as shared code reads no entity: `SpecTree`
 * is the shape `entities/rule-version`'s `SpecNode` has (the kernel's predicate tree read from
 * its mapping), and `SpecWords` the part of `entities/ontology`'s `Ontology` the words need.
 */
export type SpecValue = string | number | boolean;

export type SpecTree =
  | { kind: "all_of"; items: readonly SpecTree[] }
  | { kind: "any_of"; items: readonly SpecTree[] }
  | { kind: "not"; item: SpecTree }
  | {
      kind: "predicate";
      attribute: string;
      operator: string | null;
      values: readonly SpecValue[];
      multi: boolean;
      freeText: string;
    }
  | { kind: "unreadable"; raw: unknown };

export interface SpecAttributeWords {
  key: string;
  definition: string;
  options: readonly { value: string; label: string }[];
}

export interface SpecWords {
  attributes: readonly SpecAttributeWords[];
}

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

function attributeWords(words: SpecWords, key: string): SpecAttributeWords | undefined {
  return words.attributes.find((attribute) => attribute.key === key);
}

/** A value in the ontology's words: an option's label, Yes or No, or the value as stored. */
export function valueWords(value: SpecValue, attribute: SpecAttributeWords | undefined): string {
  if (typeof value === "boolean") {
    return value ? t("ruleVersion.value.yes") : t("ruleVersion.value.no");
  }
  const text = String(value);
  if (attribute === undefined) return text;
  return attribute.options.find((option) => option.value === text)?.label ?? text;
}

function predicateLine(
  node: Extract<SpecTree, { kind: "predicate" }>,
  words: SpecWords | null,
): SpecLine {
  const attribute = words === null ? undefined : attributeWords(words, node.attribute);
  const values = node.values.map((value) => valueWords(value, attribute)).join(", ");
  return {
    kind: "predicate",
    attribute: node.attribute,
    definition: attribute?.definition ?? null,
    inOntology: words === null || attribute !== undefined,
    condition: node.operator === null ? null : `${operatorWords(node.operator)} ${values}`,
    judgement: node.freeText === "" ? null : node.freeText,
  };
}

/**
 * The tree in words. `words` is null when the ontology could not be read: the values are then
 * shown as stored, no attribute is called unknown and no meaning is given.
 */
export function describeSpecification(node: SpecTree, words: SpecWords | null): SpecLine {
  switch (node.kind) {
    case "all_of":
    case "any_of":
      return {
        kind: "group",
        mode: node.kind,
        lead: t(LEADS[node.kind]),
        items: node.items.map((item) => describeSpecification(item, words)),
      };
    case "not":
      return {
        kind: "group",
        mode: "not",
        lead: t(LEADS.not),
        items: [describeSpecification(node.item, words)],
      };
    case "predicate":
      return predicateLine(node, words);
    case "unreadable":
      return { kind: "unreadable", json: JSON.stringify(node.raw) ?? String(node.raw) };
  }
}

/**
 * The words as plain lines, two spaces deeper per level, as the rulebook describes a
 * specification: what a comparison of two conditions reads line by line.
 */
export function specificationText(line: SpecLine, depth = 0): string[] {
  const indent = "  ".repeat(depth);
  switch (line.kind) {
    case "group":
      return [
        `${indent}${line.lead}`,
        ...line.items.flatMap((item) => specificationText(item, depth + 1)),
      ];
    case "predicate": {
      const head = [line.attribute, line.condition].filter((part) => part !== null).join(" ");
      return line.judgement === null
        ? [`${indent}${head}`]
        : [
            `${indent}${head}`,
            `${indent}  ${t("ruleVersion.spec.judgement", { text: line.judgement })}`,
          ];
    }
    case "unreadable":
      return [`${indent}${t("ruleVersion.spec.unreadable")} ${line.json}`];
  }
}

export interface SpecificationViewProps {
  line: SpecLine;
}

function Line({ line }: { line: SpecLine }) {
  switch (line.kind) {
    case "group":
      return (
        <div data-slot="spec-group" data-mode={line.mode} className="flex flex-col gap-2">
          <p className="text-sm font-medium text-fg">{line.lead}</p>
          {line.items.length === 0 ? (
            <p className="ml-5 text-sm text-fg-muted" data-slot="spec-empty-group">
              {line.mode === "any_of"
                ? t("ruleVersion.spec.emptyAnyOf")
                : t("ruleVersion.spec.emptyAllOf")}
            </p>
          ) : (
            <ul className="ml-5 flex list-disc flex-col gap-2">
              {line.items.map((item, index) => (
                <li key={index} className="text-sm">
                  <Line line={item} />
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    case "predicate":
      return (
        <div
          data-slot="spec-predicate"
          data-attribute={line.attribute}
          className="flex flex-col gap-1"
        >
          <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-sm text-fg">
            <code className="rounded-sm bg-surface px-1 font-mono text-xs">{line.attribute}</code>
            {line.condition === null ? null : <span>{line.condition}</span>}
            {line.inOntology ? null : (
              <Badge tone="warning">{t("ruleVersion.spec.notInOntology")}</Badge>
            )}
          </p>
          {line.judgement === null ? null : (
            <p className="text-sm text-fg" data-slot="spec-judgement">
              {t("ruleVersion.spec.judgement", { text: line.judgement })}
            </p>
          )}
          {line.definition === null ? null : (
            <p className="text-xs text-fg-muted">{line.definition}</p>
          )}
        </div>
      );
    case "unreadable":
      return (
        <div data-slot="spec-unreadable" className="flex flex-col gap-1">
          <p className="text-sm text-fg">{t("ruleVersion.spec.unreadable")}</p>
          <code className="font-mono text-xs break-all text-fg-muted">{line.json}</code>
        </div>
      );
  }
}

/**
 * A condition in words: the groups that combine predicates, then each predicate with its
 * attribute, the condition worded with the ontology's labels, what an analyst has to judge where
 * it is free text, and the ontology's meaning of the attribute.
 */
export function SpecificationView({ line }: SpecificationViewProps) {
  return (
    <div data-slot="specification" className="flex flex-col gap-2">
      <Line line={line} />
    </div>
  );
}
