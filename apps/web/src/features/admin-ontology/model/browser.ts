import { toAwaitedItem } from "@/entities/screen/mappers";
import type { AwaitedItemView } from "@/entities/screen/types";
import { operatorsFor, optionLabel } from "@/entities/ontology/mappers";
import {
  ATTRIBUTE_LEVELS,
  type AttributeLevel,
  type AttributeSource,
  type AttributeType,
  type Ontology,
  type OntologyAttribute,
  type OntologyOption,
} from "@/entities/ontology/types";
import { screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate, isDateKey } from "@/shared/lib/dates";

/**
 * The ontology browser's model: the attributes `GET /v1/ontology` serves, grouped by the level of
 * the business hierarchy that holds them (ADR-016) and kept in the ontology's order, which is the
 * order onboarding asks in. Every word about an attribute is the service's; the labels here name
 * the kernel's kinds (level, source, type), not regulatory facts.
 */
const LEVEL_LABEL: Readonly<Record<AttributeLevel, MessageKey>> = {
  entity: "ontology.level.entity",
  registration: "ontology.level.registration",
  location: "ontology.level.location",
};

const SOURCE_LABEL: Readonly<Record<AttributeSource, MessageKey>> = {
  gstin_lookup: "ontology.source.gstin_lookup",
  user_input: "ontology.source.user_input",
  derived: "ontology.source.derived",
};

const TYPE_LABEL: Readonly<Record<AttributeType, MessageKey>> = {
  enum: "ontology.type.enum",
  ordered_enum: "ontology.type.ordered_enum",
  enum_set: "ontology.type.enum_set",
  boolean: "ontology.type.boolean",
  integer: "ontology.type.integer",
  decimal: "ontology.type.decimal",
  date: "ontology.type.date",
  string: "ontology.type.string",
};

export interface AttributeRow {
  key: string;
  typeLabel: string;
  sourceLabel: string;
  perFinancialYear: boolean;
  definition: string;
  /** Empty for an attribute onboarding does not ask about (a derived one). */
  question: string;
  help: string;
  options: readonly OntologyOption[];
  /** The bounds of a number, in words; null without any. */
  range: string | null;
  /** The ontology's example value, worded with the value labels; null without one. */
  example: string | null;
  /** The operators a rule predicate may use on the attribute's type. */
  operators: readonly string[];
}

export interface LevelSection {
  level: AttributeLevel;
  label: string;
  attributes: AttributeRow[];
}

export interface OntologyBrowserView {
  version: string;
  wordingVersion: string;
  language: string;
  reviewStatus: string;
  wordingReviewed: boolean;
  total: number;
  /** The levels that hold at least one attribute, entity first. */
  sections: LevelSection[];
  /** Keys of attributes whose type, level or source the web app does not know. */
  unsupported: readonly string[];
}

/** The bounds of a whole or decimal number: "0 to 1000", "0 or more", "Up to 10". */
export function rangeText(min: number | null, max: number | null): string | null {
  if (min !== null && max !== null) return t("ontology.range.between", { min, max });
  if (min !== null) return t("ontology.range.min", { min });
  if (max !== null) return t("ontology.range.max", { max });
  return null;
}

/** The example in words: value labels for the option types, Yes or No, a date in IST. */
export function exampleText(attribute: OntologyAttribute): string | null {
  const { example } = attribute;
  if (example === null || example === undefined) return null;
  if (typeof example === "boolean") return example ? t("attribute.yes") : t("attribute.no");
  if (Array.isArray(example)) {
    return example.map((value) => optionLabel(attribute, String(value))).join(", ");
  }
  if (typeof example === "string") {
    if (attribute.type === "date" && isDateKey(example)) return formatDate(example);
    return attribute.options.length > 0 ? optionLabel(attribute, example) : example;
  }
  if (typeof example === "number") return String(example);
  return JSON.stringify(example);
}

export function attributeRow(ontology: Ontology, attribute: OntologyAttribute): AttributeRow {
  return {
    key: attribute.key,
    typeLabel: t(TYPE_LABEL[attribute.type]),
    sourceLabel: t(SOURCE_LABEL[attribute.source]),
    perFinancialYear: attribute.perFinancialYear,
    definition: attribute.definition,
    question: attribute.question.trim(),
    help: attribute.help.trim(),
    options: attribute.options,
    range: rangeText(attribute.min, attribute.max),
    example: exampleText(attribute),
    operators: operatorsFor(ontology, attribute.type),
  };
}

export function ontologyBrowserView(ontology: Ontology): OntologyBrowserView {
  const sections = ATTRIBUTE_LEVELS.map((level) => ({
    level,
    label: t(LEVEL_LABEL[level]),
    attributes: ontology.attributes
      .filter((attribute) => attribute.level === level)
      .sort((a, b) => a.order - b.order)
      .map((attribute) => attributeRow(ontology, attribute)),
  })).filter((section) => section.attributes.length > 0);
  return {
    version: ontology.version,
    wordingVersion: ontology.wordingVersion,
    language: ontology.language,
    reviewStatus: ontology.reviewStatus,
    wordingReviewed: ontology.wordingReviewed,
    total: ontology.attributes.length,
    sections,
    unsupported: ontology.unsupported,
  };
}

/** What the page says about the usage counts: the registry entry that waits for them. */
export interface UsageNote {
  title: string;
  waitingFor: AwaitedItemView[];
}

export function usageNote(): UsageNote {
  const usage = screenById("admin.ontology.usage");
  return { title: usage.title, waitingFor: usage.awaits.map(toAwaitedItem) };
}
