import type {
  AttributeValue,
  Business,
  Onboarding,
  ProfileNode,
  Question,
  QuestionState,
} from "@/entities/business/types";
import { attributeOf, isAnswerable, isAttributeType } from "@/entities/ontology/mappers";
import type { Ontology, OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";

/**
 * The questions step's logic, pure: which question to ask, and the list of questions a person
 * answered "Not sure" to in this run.
 *
 * The business API's checklist (`GET /v1/businesses/{id}/onboarding`) lists one item per
 * answerable attribute of the entity, then of each registration in the order they were created,
 * in the ontology's order within a node, and names the first one that is missing or unsure as
 * `next`. It counts an unsure answer as open, so after "Not sure" it asks the same question
 * again. The step therefore keeps a skip list (the httpOnly cookie in `skip-list.ts`, one per
 * business, for a day) and, when `next` is on it, walks the same checklist over the business's
 * stored values to find the first open item that is not. When nothing is left, the step is done
 * for this run; the summary lists what was left unsure.
 */
export const SKIP_COOKIE_PREFIX = "cw_onboarding_skip_";

/** The most items the cookie keeps; more than any checklist holds today. */
export const SKIP_LIST_LIMIT = 200;

const SKIP_ITEM =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[a-z][a-z0-9_]{0,63}$/;

export function skipCookieName(businessId: string): string {
  return `${SKIP_COOKIE_PREFIX}${businessId}`;
}

/** One checklist item: the node the answer is stored on, and the attribute. */
export function skipKey(nodeId: string, key: string): string {
  return `${nodeId}:${key}`;
}

/** The skip list a cookie holds; anything malformed is dropped rather than trusted. */
export function parseSkipList(raw: string | undefined): Set<string> {
  if (raw === undefined || raw === "") return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed
        .filter((item): item is string => typeof item === "string" && SKIP_ITEM.test(item))
        .slice(0, SKIP_LIST_LIMIT),
    );
  } catch {
    return new Set();
  }
}

export function serialiseSkipList(items: ReadonlySet<string>): string {
  return JSON.stringify([...items].sort().slice(0, SKIP_LIST_LIMIT));
}

/** The list with the item added (an unsure answer) or removed (any other answer). */
export function withSkip(items: ReadonlySet<string>, item: string, skip: boolean): Set<string> {
  const next = new Set(items);
  if (skip) next.add(item);
  else next.delete(item);
  return next;
}

export interface ChecklistItem {
  nodeId: string;
  level: string;
  key: string;
  state: QuestionState;
  perFinancialYear: boolean;
}

function stateOf(stored: AttributeValue | undefined): QuestionState {
  return stored === undefined ? "missing" : stored.state;
}

interface WalkedItem extends ChecklistItem {
  attribute: OntologyAttribute;
}

function walk(business: Business, ontology: Ontology, fy: string): WalkedItem[] {
  const nodes: { id: string; level: string; values: readonly AttributeValue[] }[] = [
    { id: business.id, level: "entity", values: business.attributes },
    ...business.registrations.map((node) => ({
      id: node.id,
      level: node.level,
      values: node.attributes,
    })),
  ];
  return nodes.flatMap((node) =>
    ontology.attributes
      .filter((attribute) => attribute.level === node.level && isAnswerable(attribute))
      .map((attribute) => {
        const stored = node.values.find(
          (value) =>
            value.key === attribute.key &&
            value.asOfFy === (attribute.perFinancialYear ? fy : null),
        );
        return {
          nodeId: node.id,
          level: node.level,
          key: attribute.key,
          state: stateOf(stored),
          perFinancialYear: attribute.perFinancialYear,
          attribute,
        };
      }),
  );
}

/**
 * The business's checklist as the service builds it: the entity, then each registration, and
 * for each node its level's answerable attributes in ontology order, with the stored state for
 * `fy` when the attribute is stated per year.
 */
export function checklistItems(
  business: Business,
  ontology: Ontology,
  fy: string,
): ChecklistItem[] {
  return walk(business, ontology, fy).map((item) => ({
    nodeId: item.nodeId,
    level: item.level,
    key: item.key,
    state: item.state,
    perFinancialYear: item.perFinancialYear,
  }));
}

function isOpen(item: { state: QuestionState }): boolean {
  return item.state === "missing" || item.state === "unsure";
}

function questionFrom(item: ChecklistItem, attribute: OntologyAttribute, fy: string): Question {
  return {
    nodeId: item.nodeId,
    level: item.level,
    key: item.key,
    state: item.state,
    perFinancialYear: item.perFinancialYear,
    asOfFy: item.perFinancialYear ? fy : null,
    type: attribute.type,
    question: attribute.question,
    help: attribute.help,
    options: attribute.options,
    min: attribute.min,
    max: attribute.max,
  };
}

/**
 * The question to ask now: the checklist's `next` unless it is on the skip list, else the first
 * open item of the local walk that is not; null when nothing is left in this run.
 */
export function pickQuestion(
  onboarding: Onboarding,
  business: Business,
  ontology: Ontology,
  skipped: ReadonlySet<string>,
): Question | null {
  const { next } = onboarding;
  if (next === null) return null;
  if (!skipped.has(skipKey(next.nodeId, next.key))) return next;
  const item = walk(business, ontology, onboarding.asOfFy).find(
    (candidate) => isOpen(candidate) && !skipped.has(skipKey(candidate.nodeId, candidate.key)),
  );
  return item === undefined ? null : questionFrom(item, item.attribute, onboarding.asOfFy);
}

/**
 * The attribute a question's control is drawn from: the ontology's, or one made from the
 * question itself when the ontology the web server holds does not have it yet (a release the
 * cache has not seen). A type the controls do not know gives undefined.
 */
export function attributeForQuestion(
  question: Question,
  ontology: Ontology,
): OntologyAttribute | undefined {
  const known = attributeOf(ontology, question.key);
  if (known !== undefined) return known;
  if (!isAttributeType(question.type)) return undefined;
  return {
    key: question.key,
    type: question.type,
    level: question.level === "registration" ? "registration" : "entity",
    source: "user_input",
    perFinancialYear: question.perFinancialYear,
    definition: question.help,
    question: question.question,
    help: question.help,
    options: question.options,
    min: question.min,
    max: question.max,
    example: null,
    order: Number.MAX_SAFE_INTEGER,
  };
}

/** What a question is about: the business by its PAN, or one registration by its GSTIN. */
export function nodeLabel(business: Business, nodeId: string): string {
  if (nodeId === business.id) {
    return t("question.aboutBusiness", { name: business.name, pan: business.pan });
  }
  const registration = business.registrations.find((node) => node.id === nodeId);
  return registration === undefined
    ? t("question.aboutNode", { id: nodeId })
    : t("question.aboutRegistration", { name: registration.name, gstin: registration.key });
}

/** The business's nodes the review tasks can be on: the entity and its registrations. */
export function businessNodes(business: Business): ProfileNode[] {
  return [
    {
      id: business.id,
      level: "entity",
      key: business.pan,
      name: business.name,
      parentId: null,
      version: business.version,
      attributes: business.attributes,
      created: false,
    },
    ...business.registrations,
  ];
}
