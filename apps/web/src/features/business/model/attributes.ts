import type { AttributeValue, ValueState } from "@/entities/business/types";
import { attributeOf, compareByOntologyOrder, isAnswerable } from "@/entities/ontology/mappers";
import type { AttributeLevel, Ontology, OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { describeValue, stateLabel } from "./values";

/**
 * The rows of an attributes table: one per stored value (a per-year attribute has one per
 * year), in ontology order, worded by the ontology, with the state, the year, where the value
 * came from and when it changed. An attribute the ontology does not hold keeps its key as the
 * label and its raw value, rather than disappearing.
 */
export interface AttributeRow {
  /** Unique per row: the key, and the year for a per-year value. */
  id: string;
  key: string;
  label: string;
  /** The ontology's definition, for a details element; empty for an unknown attribute. */
  definition: string;
  state: ValueState;
  stateLabel: string;
  valueText: string;
  asOfFy: string | null;
  source: string;
  sourceLabel: string;
  /** In IST, or null when the service has no time for it. */
  updatedAt: string | null;
  /** The attribute as the ontology defines it; undefined when it does not. */
  attribute: OntologyAttribute | undefined;
}

/** An attribute's name in a table or a heading: its key read as a sentence. */
export function attributeLabel(key: string): string {
  return humanise(key);
}

export function sourceLabel(source: string): string {
  switch (source) {
    case "gstin_lookup":
    case "user_input":
    case "derived":
      return t(`attribute.source.${source}`);
    default:
      return humanise(source);
  }
}

export function attributeRows(
  ontology: Ontology,
  values: readonly AttributeValue[],
): AttributeRow[] {
  const byOrder = compareByOntologyOrder(ontology);
  return [...values]
    .sort(
      (a, b) =>
        byOrder(a.key, b.key) ||
        // Newest year first for a per-year attribute.
        (b.asOfFy ?? "").localeCompare(a.asOfFy ?? ""),
    )
    .map((stored) => {
      const attribute = attributeOf(ontology, stored.key);
      return {
        id: stored.asOfFy === null ? stored.key : `${stored.key}@${stored.asOfFy}`,
        key: stored.key,
        label: attributeLabel(stored.key),
        definition: attribute?.definition ?? "",
        state: stored.state,
        stateLabel: stateLabel(stored.state),
        valueText: describeValue(attribute, stored),
        asOfFy: stored.asOfFy,
        source: stored.source,
        sourceLabel: sourceLabel(stored.source),
        updatedAt: stored.updatedAt === null ? null : formatDateTime(stored.updatedAt),
        attribute,
      };
    });
}

/**
 * The answerable attributes of the given levels that hold no value yet: for a per-year
 * attribute, none for `fy`. Derived attributes are never listed; the service works them out.
 */
export function unansweredAttributes(
  ontology: Ontology,
  levels: readonly AttributeLevel[],
  values: readonly AttributeValue[],
  fy: string,
): OntologyAttribute[] {
  return ontology.attributes.filter(
    (attribute) =>
      isAnswerable(attribute) &&
      levels.includes(attribute.level) &&
      !values.some(
        (stored) =>
          stored.key === attribute.key &&
          (attribute.perFinancialYear ? stored.asOfFy === fy : true),
      ),
  );
}

/** Known, unsure and not-applicable counts over a node's values, for a tile or a summary. */
export function stateCounts(values: readonly AttributeValue[]): Record<ValueState, number> {
  const counts: Record<ValueState, number> = { known: 0, unsure: 0, not_applicable: 0 };
  for (const stored of values) counts[stored.state] += 1;
  return counts;
}
