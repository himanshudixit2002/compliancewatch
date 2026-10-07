import { t } from "@/shared/i18n";

/**
 * The predicate editor's tree: the kernel's grammar (domain_kernel.predicates) as the editor
 * holds it while an analyst builds a condition. Groups are `{"all_of": [...]}` and
 * `{"any_of": [...]}`, a negation is `{"not": {...}}`, and a predicate names an attribute with an
 * operator and a value (a list for the multi-value operators), or free text a person has to
 * judge, or both (the comparison then only hints). Values are strings, numbers or booleans.
 *
 * Each node has an id for the editor's controls and errors. A part of a stored condition the
 * editor cannot read is kept whole (`raw`) and written back as it was, so opening a condition
 * never changes it. Everything here checks the shape only; the rulebook checks the condition
 * against the ontology for real when the draft is saved.
 */
export type ValueType = "string" | "number" | "boolean";

export interface PredicateDraft {
  kind: "predicate";
  id: string;
  attribute: string;
  /** The kernel's operator, or "" for free text alone. */
  operator: string;
  /** The values as typed: one for a single-value operator, any number for a multi-value one. */
  values: string[];
  /** The JSON type each value had when it was read, for an attribute the ontology lacks. */
  types: ValueType[];
  freeText: string;
}

export interface GroupDraft {
  kind: "all_of" | "any_of";
  id: string;
  items: NodeDraft[];
}

export interface NotDraft {
  kind: "not";
  id: string;
  item: NodeDraft;
}

export interface RawDraft {
  kind: "raw";
  id: string;
  raw: unknown;
}

export type NodeDraft = GroupDraft | NotDraft | PredicateDraft | RawDraft;

/** What the editor needs of the ontology: each attribute's key, type, meaning and options. */
export interface EditorAttribute {
  key: string;
  type: string;
  definition: string;
  options: readonly { value: string; label: string }[];
}

export interface EditorOntology {
  attributes: readonly EditorAttribute[];
  operatorsByType: Readonly<Record<string, readonly string[]>>;
}

/** The operators whose value is a list (domain_kernel.operators.MULTI_VALUE_OPERATORS). */
export const MULTI_VALUE_OPERATORS: readonly string[] = ["in", "not_in", "contains_any"];

/** Every operator the kernel knows, for an attribute the ontology does not hold. */
export const KERNEL_OPERATORS: readonly string[] = [
  "eq",
  "neq",
  "in",
  "not_in",
  "gt",
  "gte",
  "lt",
  "lte",
  "contains",
  "contains_any",
];

/** domain_kernel.ontology.ATTRIBUTE_KEY_PATTERN. */
export const ATTRIBUTE_KEY = /^[a-z][a-z0-9_]*$/;

const PREDICATE_KEYS = new Set(["attribute", "operator", "value", "free_text"]);

export type IdSource = () => string;

/** Ids n0, n1, ... unique within one editor. */
export function idSource(prefix = "n"): IdSource {
  let next = 0;
  return () => `${prefix}${next++}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isScalar(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function typeOf(value: string | number | boolean): ValueType {
  return typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "string";
}

export function isMulti(operator: string): boolean {
  return MULTI_VALUE_OPERATORS.includes(operator);
}

export function emptyPredicate(id: string, attribute = ""): PredicateDraft {
  return { kind: "predicate", id, attribute, operator: "", values: [], types: [], freeText: "" };
}

export function emptyGroup(id: string, kind: "all_of" | "any_of" = "all_of"): GroupDraft {
  return { kind, id, items: [] };
}

/**
 * The tree from a stored mapping. An empty mapping (a draft with no condition yet) and nothing
 * at all open as an empty "all of" group; a part of an unknown shape is kept whole.
 */
export function fromMapping(raw: unknown, newId: IdSource): NodeDraft {
  if (raw === null || raw === undefined || (isRecord(raw) && Object.keys(raw).length === 0)) {
    return emptyGroup(newId());
  }
  return nodeFrom(raw, newId);
}

function nodeFrom(raw: unknown, newId: IdSource): NodeDraft {
  if (!isRecord(raw)) return { kind: "raw", id: newId(), raw };
  const keys = Object.keys(raw);
  if (keys.length === 1 && Array.isArray(raw.all_of)) {
    return { kind: "all_of", id: newId(), items: raw.all_of.map((item) => nodeFrom(item, newId)) };
  }
  if (keys.length === 1 && Array.isArray(raw.any_of)) {
    return { kind: "any_of", id: newId(), items: raw.any_of.map((item) => nodeFrom(item, newId)) };
  }
  if (keys.length === 1 && "not" in raw) {
    return { kind: "not", id: newId(), item: nodeFrom(raw.not, newId) };
  }
  if (typeof raw.attribute !== "string" || !keys.every((key) => PREDICATE_KEYS.has(key))) {
    return { kind: "raw", id: newId(), raw };
  }
  const value = raw.value;
  const list: unknown[] = Array.isArray(value)
    ? value
    : value === undefined || value === null
      ? []
      : [value];
  const operator = typeof raw.operator === "string" ? raw.operator : "";
  const freeText = typeof raw.free_text === "string" ? raw.free_text : "";
  if (
    !list.every(isScalar) ||
    (raw.operator !== undefined && raw.operator !== null && typeof raw.operator !== "string") ||
    (raw.free_text !== undefined && typeof raw.free_text !== "string")
  ) {
    return { kind: "raw", id: newId(), raw };
  }
  const scalars = list as (string | number | boolean)[];
  return {
    kind: "predicate",
    id: newId(),
    attribute: raw.attribute,
    operator,
    values: scalars.map((item) => String(item)),
    types: scalars.map(typeOf),
    freeText,
  };
}

export function attributeOf(
  ontology: EditorOntology | null,
  key: string,
): EditorAttribute | undefined {
  return ontology?.attributes.find((attribute) => attribute.key === key);
}

/** The operators the ontology allows on the attribute's type; every kernel one for an unknown. */
export function operatorsFor(ontology: EditorOntology | null, key: string): readonly string[] {
  const attribute = attributeOf(ontology, key);
  if (attribute === undefined) return KERNEL_OPERATORS;
  return ontology?.operatorsByType[attribute.type] ?? [];
}

/** The JSON type a value of the attribute is written as, in the kernel's canonical forms. */
function valueTypeFor(
  attribute: EditorAttribute | undefined,
  stored: ValueType | undefined,
): ValueType {
  if (attribute === undefined) return stored ?? "string";
  switch (attribute.type) {
    case "boolean":
      return "boolean";
    case "integer":
      return "number";
    default:
      // enums, sets, strings, and decimals and dates, which the kernel writes as strings.
      return "string";
  }
}

function scalarOf(text: string, type: ValueType): string | number | boolean {
  if (type === "boolean") return text === "true";
  if (type === "number") return Number(text);
  return text;
}

/** The kernel's mapping of the tree, as the rulebook stores a specification. */
export function toMapping(node: NodeDraft, ontology: EditorOntology | null): unknown {
  switch (node.kind) {
    case "all_of":
      return { all_of: node.items.map((item) => toMapping(item, ontology)) };
    case "any_of":
      return { any_of: node.items.map((item) => toMapping(item, ontology)) };
    case "not":
      return { not: toMapping(node.item, ontology) };
    case "raw":
      return node.raw;
    case "predicate": {
      const attribute = attributeOf(ontology, node.attribute);
      const freeText = node.freeText.trim();
      if (node.operator === "") return { attribute: node.attribute, free_text: freeText };
      const multi = isMulti(node.operator);
      const scalars = node.values
        .map((text, index) => ({
          text: text.trim(),
          type: valueTypeFor(attribute, node.types[index]),
        }))
        .filter((value) => !multi || value.text !== "")
        .map((value) => scalarOf(value.text, value.type));
      const mapping: Record<string, unknown> = {
        attribute: node.attribute,
        operator: node.operator,
        value: multi ? scalars : (scalars[0] ?? ""),
      };
      if (freeText !== "") mapping.free_text = freeText;
      return mapping;
    }
  }
}

/** Where an error belongs: a node's field, as `<id>.<field>`. */
export function errorKey(
  id: string,
  field: "attribute" | "operator" | "value" | "freeText" | "items",
): string {
  return `${id}.${field}`;
}

function valueProblem(text: string, attribute: EditorAttribute | undefined): string | null {
  const value = text.trim();
  if (value === "") return t("predicateEditor.error.valueEmpty");
  if (attribute === undefined) return null;
  switch (attribute.type) {
    case "integer":
      return /^-?\d+$/.test(value) ? null : t("predicateEditor.error.integer");
    case "decimal":
      return /^-?\d+(\.\d+)?$/.test(value) ? null : t("predicateEditor.error.decimal");
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(value) ? null : t("predicateEditor.error.date");
    case "boolean":
      return value === "true" || value === "false" ? null : t("predicateEditor.error.boolean");
    default:
      return attribute.options.length > 0 &&
        !attribute.options.some((option) => option.value === value)
        ? t("predicateEditor.error.option")
        : null;
  }
}

/**
 * The shape problems of the tree, each under its node's field. Shape only: an attribute key in
 * the kernel's pattern, an operator and a value together or free text, the operator one the
 * ontology allows on the attribute, a value that reads as the attribute's type, and a "not" with
 * its one part. Whether the condition is right is the rulebook's and the analyst's to judge.
 */
export function validateTree(
  node: NodeDraft,
  ontology: EditorOntology | null,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const visit = (current: NodeDraft): void => {
    switch (current.kind) {
      case "all_of":
      case "any_of":
        current.items.forEach(visit);
        return;
      case "not":
        visit(current.item);
        return;
      case "raw":
        return;
      case "predicate": {
        if (!ATTRIBUTE_KEY.test(current.attribute)) {
          errors[errorKey(current.id, "attribute")] =
            current.attribute === ""
              ? t("predicateEditor.error.attributeEmpty")
              : t("predicateEditor.error.attributeShape");
        }
        const attribute = attributeOf(ontology, current.attribute);
        if (current.operator === "") {
          if (current.freeText.trim() === "") {
            errors[errorKey(current.id, "freeText")] = t("predicateEditor.error.nothing");
          }
          return;
        }
        if (
          ontology !== null &&
          attribute !== undefined &&
          !operatorsFor(ontology, current.attribute).includes(current.operator)
        ) {
          errors[errorKey(current.id, "operator")] = t("predicateEditor.error.operator");
          return;
        }
        const values = isMulti(current.operator)
          ? current.values.filter((value) => value.trim() !== "")
          : current.values.slice(0, 1);
        if (values.length === 0) {
          errors[errorKey(current.id, "value")] = isMulti(current.operator)
            ? t("predicateEditor.error.valuesEmpty")
            : t("predicateEditor.error.valueEmpty");
          return;
        }
        for (const value of values) {
          const problem = valueProblem(value, attribute);
          if (problem !== null) {
            errors[errorKey(current.id, "value")] = problem;
            return;
          }
        }
        return;
      }
    }
  };
  visit(node);
  return errors;
}

/**
 * Whether a parsed JSON value has the kernel's shape: the groups take lists, a negation one part,
 * a predicate the four keys at most with an attribute, an operator only with a value, and every
 * value a string, a number or a boolean (or a list of them). Null when it does; otherwise the
 * first problem, worded.
 */
export function shapeProblem(raw: unknown, where = "specification"): string | null {
  if (!isRecord(raw)) return t("predicateEditor.json.notObject", { where });
  const keys = Object.keys(raw);
  if (keys.length === 1 && "all_of" in raw) return listProblem(raw.all_of, `${where}.all_of`);
  if (keys.length === 1 && "any_of" in raw) return listProblem(raw.any_of, `${where}.any_of`);
  if (keys.length === 1 && "not" in raw) return shapeProblem(raw.not, `${where}.not`);
  if (!("attribute" in raw) || !keys.every((key) => PREDICATE_KEYS.has(key))) {
    return t("predicateEditor.json.keys", { where });
  }
  if (typeof raw.attribute !== "string" || !ATTRIBUTE_KEY.test(raw.attribute)) {
    return t("predicateEditor.json.attribute", { where });
  }
  const hasOperator = raw.operator !== undefined && raw.operator !== null;
  const hasValue = raw.value !== undefined && raw.value !== null;
  if (hasOperator !== hasValue) return t("predicateEditor.json.together", { where });
  if (hasOperator && typeof raw.operator !== "string") {
    return t("predicateEditor.json.operator", { where });
  }
  if (hasValue) {
    const values = Array.isArray(raw.value) ? raw.value : [raw.value];
    if (!values.every(isScalar)) return t("predicateEditor.json.value", { where });
  }
  if (raw.free_text !== undefined && typeof raw.free_text !== "string") {
    return t("predicateEditor.json.freeText", { where });
  }
  const freeText = typeof raw.free_text === "string" ? raw.free_text.trim() : "";
  if (!hasOperator && freeText === "") return t("predicateEditor.json.nothing", { where });
  return null;
}

function listProblem(items: unknown, where: string): string | null {
  if (!Array.isArray(items)) return t("predicateEditor.json.list", { where });
  for (const [index, item] of items.entries()) {
    const problem = shapeProblem(item, `${where}[${index}]`);
    if (problem !== null) return problem;
  }
  return null;
}

/** The JSON view's text read back: the tree, or the first shape problem worded. */
export function parseJson(
  text: string,
  newId: IdSource,
): { ok: true; node: NodeDraft } | { ok: false; problem: string } {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, problem: t("predicateEditor.json.syntax") };
  }
  const problem = shapeProblem(raw);
  if (problem !== null) return { ok: false, problem };
  return { ok: true, node: fromMapping(raw, newId) };
}

/** The JSON view's text: the mapping, two spaces deep. */
export function toJson(node: NodeDraft, ontology: EditorOntology | null): string {
  return JSON.stringify(toMapping(node, ontology), null, 2);
}

// ---- Changes: each returns a new tree and leaves the old one as it was ----------------------------

export function mapNode(
  node: NodeDraft,
  id: string,
  change: (found: NodeDraft) => NodeDraft,
): NodeDraft {
  if (node.id === id) return change(node);
  switch (node.kind) {
    case "all_of":
    case "any_of": {
      const items = node.items.map((item) => mapNode(item, id, change));
      return items.every((item, index) => item === node.items[index]) ? node : { ...node, items };
    }
    case "not": {
      const item = mapNode(node.item, id, change);
      return item === node.item ? node : { ...node, item };
    }
    default:
      return node;
  }
}

/** The node with this id, or undefined. */
export function findNode(node: NodeDraft, id: string): NodeDraft | undefined {
  if (node.id === id) return node;
  switch (node.kind) {
    case "all_of":
    case "any_of":
      for (const item of node.items) {
        const found = findNode(item, id);
        if (found !== undefined) return found;
      }
      return undefined;
    case "not":
      return findNode(node.item, id);
    default:
      return undefined;
  }
}

/** A part added at the end of a group. */
export function addTo(root: NodeDraft, groupId: string, child: NodeDraft): NodeDraft {
  return mapNode(root, groupId, (found) =>
    found.kind === "all_of" || found.kind === "any_of"
      ? { ...found, items: [...found.items, child] }
      : found,
  );
}

/**
 * The tree without the node. A negation whose one part goes goes with it, since a "not" always
 * holds one part; the root is never removed (an empty "all of" stands in for nothing).
 */
export function removeNode(root: NodeDraft, id: string): NodeDraft {
  if (root.id === id) return root;
  const prune = (node: NodeDraft): NodeDraft | null => {
    if (node.id === id) return null;
    switch (node.kind) {
      case "all_of":
      case "any_of": {
        const items = node.items.map(prune).filter((item): item is NodeDraft => item !== null);
        return items.length === node.items.length &&
          items.every((item, index) => item === node.items[index])
          ? node
          : { ...node, items };
      }
      case "not": {
        const item = prune(node.item);
        if (item === null) return null;
        return item === node.item ? node : { ...node, item };
      }
      default:
        return node;
    }
  };
  return prune(root) ?? root;
}

/** The node put inside a new "not" (or taken out of the one it is in). */
export function toggleNot(root: NodeDraft, id: string, newId: IdSource): NodeDraft {
  return mapNode(root, id, (found) =>
    found.kind === "not" ? found.item : { kind: "not", id: newId(), item: found },
  );
}

/** A part moved one place up or down within its group; unchanged at either end. */
export function moveNode(root: NodeDraft, id: string, step: -1 | 1): NodeDraft {
  const move = (node: NodeDraft): NodeDraft => {
    switch (node.kind) {
      case "all_of":
      case "any_of": {
        const at = node.items.findIndex((item) => item.id === id);
        if (at >= 0) {
          const to = at + step;
          if (to < 0 || to >= node.items.length) return node;
          const items = [...node.items];
          const [moved] = items.splice(at, 1);
          items.splice(to, 0, moved as NodeDraft);
          return { ...node, items };
        }
        const items = node.items.map(move);
        return items.every((item, index) => item === node.items[index]) ? node : { ...node, items };
      }
      case "not": {
        const item = move(node.item);
        return item === node.item ? node : { ...node, item };
      }
      default:
        return node;
    }
  };
  return move(root);
}

/**
 * A predicate's attribute changed: the operator and the values are kept while the new attribute
 * allows them, and cleared otherwise, so no value of another attribute's options stays behind.
 */
export function withAttribute(
  predicate: PredicateDraft,
  attribute: string,
  ontology: EditorOntology | null,
): PredicateDraft {
  const before = attributeOf(ontology, predicate.attribute);
  const after = attributeOf(ontology, attribute);
  const operatorKept =
    predicate.operator === "" || operatorsFor(ontology, attribute).includes(predicate.operator);
  // Values carry over between attributes of one type without options (two counts, two dates);
  // an option belongs to its attribute, so options never carry over to another one.
  const sameValues =
    before === undefined || after === undefined
      ? before === after
      : before.type === after.type &&
        (before.key === after.key || (before.options.length === 0 && after.options.length === 0));
  return {
    ...predicate,
    attribute,
    operator: operatorKept ? predicate.operator : "",
    values: operatorKept && sameValues ? predicate.values : [],
    types: operatorKept && sameValues ? predicate.types : [],
  };
}

/** A predicate's operator changed: one value kept for a single-value operator. */
export function withOperator(predicate: PredicateDraft, operator: string): PredicateDraft {
  if (operator === "") return { ...predicate, operator, values: [], types: [] };
  const values = isMulti(operator) ? predicate.values : predicate.values.slice(0, 1);
  return { ...predicate, operator, values, types: predicate.types.slice(0, values.length) };
}

/** A part that is not a group put in an "all of" with a new part beside it. */
export function combineRoot(root: NodeDraft, added: NodeDraft, newId: IdSource): NodeDraft {
  if (root.kind === "all_of" || root.kind === "any_of") return addTo(root, root.id, added);
  return { kind: "all_of", id: newId(), items: [root, added] };
}
