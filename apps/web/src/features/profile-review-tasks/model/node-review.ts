import type { ProfileNode, ReviewTask, Snapshot } from "@/entities/business/types";
import { attributeOf, compareByOntologyOrder, optionLabel } from "@/entities/ontology/mappers";
import type { Ontology, OntologyAttribute } from "@/entities/ontology/types";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate, formatDateTime, isDateKey } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { lookupHref } from "./lookup";

/**
 * One looked-up node as the page shows it: its facts, its open review tasks and the snapshot the
 * applicability engine evaluates for the year (the node's values with what it inherits from its
 * ancestors). Attributes are named and values worded by the ontology when it was read, and shown
 * as stored otherwise.
 */
const NUMBERS = new Intl.NumberFormat("en-IN");

const LEVELS: Readonly<Record<string, MessageKey>> = {
  entity: "profileReview.level.entity",
  registration: "profileReview.level.registration",
  location: "profileReview.level.location",
};

const REASONS: Readonly<Record<string, MessageKey>> = {
  not_applicable: "profileReview.reason.notApplicable",
  confirm_financial_year: "profileReview.reason.confirmFinancialYear",
  verify_registration: "profileReview.reason.verifyRegistration",
};

export function levelLabel(level: string): string {
  const key = LEVELS[level];
  return key === undefined ? humanise(level) : t(key);
}

export function reasonLabel(reason: string): string {
  const key = REASONS[reason];
  return key === undefined ? humanise(reason) : t(key);
}

/** An attribute's name: the ontology's definition, or its key as a sentence. */
export function attributeName(ontology: Ontology | null, key: string): string {
  const attribute = ontology === null ? undefined : attributeOf(ontology, key);
  return attribute?.definition || humanise(key);
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [String(value)];
}

/** A stored value in words, by the attribute's type; as stored when the type is not known. */
export function formatStoredValue(
  attribute: OntologyAttribute | undefined,
  value: unknown,
): string {
  if (value === null || value === undefined) return t("profileReview.noValue");
  if (attribute === undefined)
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  switch (attribute.type) {
    case "enum":
    case "ordered_enum":
      return optionLabel(attribute, String(value));
    case "enum_set": {
      const chosen = strings(value);
      return chosen.length === 0
        ? t("attribute.none")
        : chosen.map((item) => optionLabel(attribute, item)).join(", ");
    }
    case "boolean":
      return value === true
        ? t("attribute.yes")
        : value === false
          ? t("attribute.no")
          : String(value);
    case "integer":
      return typeof value === "number" ? NUMBERS.format(value) : String(value);
    case "date":
      return typeof value === "string" && isDateKey(value) ? formatDate(value) : String(value);
    default:
      return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
}

export interface NodeFacts {
  id: string;
  levelLabel: string;
  key: string;
  name: string;
  version: number;
  /** The parent in the same lookup; null for a legal entity. */
  parentId: string | null;
  parentHref: string | null;
}

export interface TaskRow {
  id: string;
  attributeKey: string;
  attributeName: string;
  reasonLabel: string;
  asOfFy: string | null;
  openedAt: string;
  open: boolean;
}

export interface SnapshotRow {
  key: string;
  name: string;
  value: string;
}

export interface NodeReviewView {
  tenantId: string;
  fy: string;
  node: NodeFacts;
  tasks: TaskRow[];
  snapshot: {
    version: number;
    level: string | null;
    lineage: readonly string[];
    rows: SnapshotRow[];
  };
  /** The ontology could not be read, so names and values are shown as stored. */
  ontologyMissing: boolean;
}

export function nodeReviewView(input: {
  pathname: string;
  tenantId: string;
  fy: string;
  node: ProfileNode;
  tasks: readonly ReviewTask[];
  snapshot: Snapshot;
  ontology: Ontology | null;
}): NodeReviewView {
  const { ontology, node } = input;
  const order =
    ontology === null
      ? (a: string, b: string) => a.localeCompare(b)
      : compareByOntologyOrder(ontology);
  return {
    tenantId: input.tenantId,
    fy: input.fy,
    node: {
      id: node.id,
      levelLabel: levelLabel(node.level),
      key: node.key,
      name: node.name,
      version: node.version,
      parentId: node.parentId,
      parentHref:
        node.parentId === null
          ? null
          : lookupHref(input.pathname, input.tenantId, node.parentId, input.fy),
    },
    tasks: [...input.tasks]
      .sort((a, b) => Number(b.open) - Number(a.open) || b.createdAt.localeCompare(a.createdAt))
      .map((task) => ({
        id: task.id,
        attributeKey: task.attributeKey,
        attributeName: attributeName(ontology, task.attributeKey),
        reasonLabel: reasonLabel(task.reason),
        asOfFy: task.asOfFy,
        openedAt: formatDateTime(task.createdAt),
        open: task.open,
      })),
    snapshot: {
      version: input.snapshot.version,
      level: input.snapshot.level,
      lineage: input.snapshot.lineage,
      rows: Object.keys(input.snapshot.attributes)
        .sort(order)
        .map((key) => ({
          key,
          name: attributeName(ontology, key),
          value: formatStoredValue(
            ontology === null ? undefined : attributeOf(ontology, key),
            input.snapshot.attributes[key],
          ),
        })),
    },
    ontologyMissing: ontology === null,
  };
}
