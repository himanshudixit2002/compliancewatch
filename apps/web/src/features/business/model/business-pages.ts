import { valueOf } from "@/entities/business/mappers";
import type {
  Business,
  Onboarding,
  ProfileNode,
  ReviewTask,
  Snapshot,
  ValueState,
} from "@/entities/business/types";
import { attributeOf, isAnswerable, questionOf } from "@/entities/ontology/mappers";
import type { Ontology, OntologyAttribute } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import {
  currentFinancialYear,
  financialYearLabel,
  parseFinancialYearLabel,
  previousFinancialYear,
} from "@/shared/lib/financial-year";
import {
  attributeLabel,
  attributeRows,
  stateCounts,
  unansweredAttributes,
  type AttributeRow,
} from "./attributes";
import { onboardingProgress, type OnboardingProgress } from "./progress";
import { businessNodes, namedBusinessNodes, nodeDisplayName } from "./questions";
import { reviewTaskRows, type ReviewTaskRow } from "./review-tasks";
import { snapshotRows, type SnapshotRow } from "./snapshot";
import { formDefault } from "./values";

/**
 * The views of a business's pages: its home, the hierarchy, a node's attributes for a financial
 * year, the snapshot and the review tasks. A business is its legal entity with its registrations
 * (the business API); a location is reached by its node id and belongs to the business when its
 * parent is one of the registrations. Values inherit downward, the nearest node winning, so a
 * node's page lists its own values and those it inherits, each with the node it comes from.
 */
export type NodeLevel = "entity" | "registration" | "location";

export interface NodeRef {
  id: string;
  level: NodeLevel;
  /** PAN, GSTIN or location label. */
  key: string;
  name: string;
  /** "Business (PAN)", "Registration (GSTIN)" or "Location". */
  levelLabel: string;
  /** The name that tells it apart: "Acme (PAN ...)", "<GSTIN> (Acme)", "<label> (Branch)". */
  display: string;
  version: number;
}

export interface BusinessHeader {
  id: string;
  name: string;
  pan: string;
  version: number;
  updatedAt: string;
  registrations: NodeRef[];
}

/** The node a page is about, with its ancestors root first (the business, a registration). */
export interface ResolvedNode {
  node: ProfileNode;
  ancestors: ProfileNode[];
}

function levelOf(level: string): NodeLevel {
  return level === "registration" || level === "location" ? level : "entity";
}

export function nodeRef(node: ProfileNode): NodeRef {
  const level = levelOf(node.level);
  return {
    id: node.id,
    level,
    key: node.key,
    name: node.name,
    levelLabel: t(`business.level.${level}`),
    display: nodeDisplayName(node),
    version: node.version,
  };
}

export function businessHeader(business: Business): BusinessHeader {
  return {
    id: business.id,
    name: business.name,
    pan: business.pan,
    version: business.version,
    updatedAt: formatDateTime(business.updatedAt),
    registrations: business.registrations.map(nodeRef),
  };
}

/**
 * The node an id names within the business: the entity (no id, or the business id), one of its
 * registrations, or `location` when that node's parent is one of them. Null otherwise: a node
 * of another business is not shown under this one.
 */
export function resolveNode(
  business: Business,
  nodeId: string | undefined,
  location?: ProfileNode,
): ResolvedNode | null {
  const [entity, ...registrations] = businessNodes(business);
  if (entity === undefined) return null;
  if (nodeId === undefined || nodeId === business.id) return { node: entity, ancestors: [] };
  const registration = registrations.find((node) => node.id === nodeId);
  if (registration !== undefined) return { node: registration, ancestors: [entity] };
  if (location === undefined || location.id !== nodeId || location.level !== "location") {
    return null;
  }
  const parent = registrations.find((node) => node.id === location.parentId);
  return parent === undefined ? null : { node: location, ancestors: [entity, parent] };
}

/** The financial years a page offers: this one and the two before, and the one asked for. */
export function financialYearChoices(selected: string, now: Date = new Date()): string[] {
  const current = currentFinancialYear(now);
  const years = new Set([
    financialYearLabel(current),
    financialYearLabel(previousFinancialYear(current)),
    financialYearLabel(previousFinancialYear(previousFinancialYear(current))),
    selected,
  ]);
  return [...years].sort().reverse();
}

/** The year in the query when it is a well-formed label, else the current one. */
export function selectedFinancialYear(value: string | undefined, now: Date = new Date()): string {
  if (value !== undefined && parseFinancialYearLabel(value) !== null) return value;
  return financialYearLabel(currentFinancialYear(now));
}

// ---- home ------------------------------------------------------------------------------------

export interface BusinessHomeView {
  header: BusinessHeader;
  progress: OnboardingProgress;
  /** Known, unsure and not-applicable values stored on the business and its registrations. */
  counts: Record<ValueState, number>;
  openTasks: number;
}

export function businessHomeView(
  business: Business,
  onboarding: Onboarding,
  tasks: readonly ReviewTask[],
): BusinessHomeView {
  return {
    header: businessHeader(business),
    progress: onboardingProgress(onboarding),
    counts: stateCounts(businessNodes(business).flatMap((node) => node.attributes)),
    openTasks: tasks.filter((task) => task.open).length,
  };
}

// ---- attributes ------------------------------------------------------------------------------

export interface OwnAttributeRow extends AttributeRow {
  /** Where "Change" leads; null when the value cannot be changed here. */
  editHref: string | null;
}

export interface InheritedAttributeRow extends AttributeRow {
  fromName: string;
}

export interface UnansweredItem {
  key: string;
  label: string;
  editHref: string | null;
}

export interface EditingAttribute {
  attribute: OntologyAttribute;
  key: string;
  label: string;
  question: string;
  /** The year the answer is for; null unless the attribute is stated per year. */
  asOfFy: string | null;
  defaultValue: string | string[] | undefined;
}

export interface AttributesView {
  header: BusinessHeader;
  node: NodeRef;
  /** The nodes the page can switch to: the business, its registrations, and a location shown. */
  nodes: NodeRef[];
  fy: string;
  fyChoices: string[];
  own: OwnAttributeRow[];
  inherited: InheritedAttributeRow[];
  unanswered: UnansweredItem[];
  editing: EditingAttribute | null;
  canEdit: boolean;
}

export interface AttributesInput {
  business: Business;
  resolved: ResolvedNode;
  ontology: Ontology;
  fy: string;
  /** The attribute key a "Change" link asked to edit. */
  edit?: string;
  canEdit: boolean;
  /** The page with this node and year and the edit form for a key open. */
  editHref: (key: string) => string;
  now?: Date;
}

/** Rows for one year: a per-year value only for that year, every other value as it is. */
function rowsForYear(ontology: Ontology, node: ProfileNode, fy: string): AttributeRow[] {
  return attributeRows(ontology, node.attributes).filter(
    (row) => row.attribute?.perFinancialYear !== true || row.asOfFy === fy,
  );
}

function editable(
  attribute: OntologyAttribute | undefined,
  node: ProfileNode,
): attribute is OntologyAttribute {
  return attribute !== undefined && isAnswerable(attribute) && attribute.level === node.level;
}

function editing(input: AttributesInput): EditingAttribute | null {
  const { edit, resolved, ontology, fy } = input;
  if (!input.canEdit || edit === undefined) return null;
  const attribute = attributeOf(ontology, edit);
  if (!editable(attribute, resolved.node)) return null;
  const asOfFy = attribute.perFinancialYear ? fy : null;
  return {
    attribute,
    key: attribute.key,
    label: attributeLabel(attribute.key),
    question: questionOf(attribute),
    asOfFy,
    defaultValue: formDefault(attribute, valueOf(resolved.node.attributes, attribute.key, asOfFy)),
  };
}

export function attributesView(input: AttributesInput): AttributesView {
  const { business, resolved, ontology, fy, canEdit } = input;
  const { node, ancestors } = resolved;
  const own = rowsForYear(ontology, node, fy).map((row) => ({
    ...row,
    editHref: canEdit && editable(row.attribute, node) ? input.editHref(row.key) : null,
  }));
  const ownKeys = new Set(own.map((row) => row.key));
  const inherited = [...ancestors].reverse().flatMap((ancestor) =>
    rowsForYear(ontology, ancestor, fy)
      .filter((row) => !ownKeys.has(row.key))
      .map((row) => ({ ...row, fromName: nodeDisplayName(ancestor) })),
  );
  const unanswered = unansweredAttributes(ontology, [levelOf(node.level)], node.attributes, fy).map(
    (attribute) => ({
      key: attribute.key,
      label: attributeLabel(attribute.key),
      editHref: canEdit ? input.editHref(attribute.key) : null,
    }),
  );
  const nodes = businessNodes(business).map(nodeRef);
  if (node.level === "location") nodes.push(nodeRef(node));
  return {
    header: businessHeader(business),
    node: nodeRef(node),
    nodes,
    fy,
    fyChoices: financialYearChoices(fy, input.now),
    own,
    inherited,
    unanswered,
    editing: editing(input),
    canEdit,
  };
}

// ---- snapshot --------------------------------------------------------------------------------

export interface SnapshotView {
  header: BusinessHeader;
  node: NodeRef;
  nodes: NodeRef[];
  fy: string;
  fyChoices: string[];
  version: number;
  rows: SnapshotRow[];
}

export function snapshotView(
  business: Business,
  resolved: ResolvedNode,
  snapshot: Snapshot,
  ontology: Ontology,
  fy: string,
  now?: Date,
): SnapshotView {
  const lineage = [...resolved.ancestors, resolved.node].map((node) => ({
    ...node,
    name: nodeDisplayName(node),
  }));
  const nodes = businessNodes(business).map(nodeRef);
  if (resolved.node.level === "location") nodes.push(nodeRef(resolved.node));
  return {
    header: businessHeader(business),
    node: nodeRef(resolved.node),
    nodes,
    fy,
    fyChoices: financialYearChoices(fy, now),
    version: snapshot.version,
    rows: snapshotRows(snapshot, lineage, ontology),
  };
}

// ---- review tasks ----------------------------------------------------------------------------

export interface ReviewTasksView {
  header: BusinessHeader;
  rows: ReviewTaskRow[];
  openCount: number;
}

export function reviewTasksView(business: Business, tasks: readonly ReviewTask[]): ReviewTasksView {
  return {
    header: businessHeader(business),
    rows: reviewTaskRows(tasks, namedBusinessNodes(business)),
    openCount: tasks.filter((task) => task.open).length,
  };
}
