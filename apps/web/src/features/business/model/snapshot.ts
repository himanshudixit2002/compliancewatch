import { valueOf } from "@/entities/business/mappers";
import type { ProfileNode, Snapshot } from "@/entities/business/types";
import { attributeOf, compareByOntologyOrder } from "@/entities/ontology/mappers";
import type { Ontology } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";
import { attributeLabel } from "./attributes";
import { formatValue } from "./values";

/**
 * A snapshot as rows, each with where its value comes from. The snapshot is what the
 * applicability engine evaluates: the node's own values and those inherited from its ancestors
 * (entity, registration, location), the nearest one winning. The origin is worked out the same
 * way over the lineage's nodes: the closest node holding a known value for the key (for the
 * snapshot's year when the attribute is stated per year). A value no node holds was worked out
 * by the service.
 */
export type SnapshotOrigin =
  { kind: "self" } | { kind: "inherited"; nodeId: string; nodeName: string } | { kind: "derived" };

export interface SnapshotRow {
  key: string;
  label: string;
  valueText: string;
  origin: SnapshotOrigin;
  originLabel: string;
}

/** The node that supplies a key's value: the snapshot's own node first, then up the lineage. */
export function originOf(
  key: string,
  snapshot: Snapshot,
  nodes: readonly ProfileNode[],
): SnapshotOrigin {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const ownId = snapshot.lineage[snapshot.lineage.length - 1];
  for (const id of [...snapshot.lineage].reverse()) {
    const node = byId.get(id);
    if (node === undefined) continue;
    const stored = valueOf(node.attributes, key, snapshot.asOfFy);
    if (stored === undefined || stored.state !== "known") continue;
    return id === ownId ? { kind: "self" } : { kind: "inherited", nodeId: id, nodeName: node.name };
  }
  return { kind: "derived" };
}

export function originLabel(origin: SnapshotOrigin): string {
  switch (origin.kind) {
    case "self":
      return t("attribute.origin.self");
    case "inherited":
      return t("attribute.origin.inherited", { name: origin.nodeName });
    case "derived":
      return t("attribute.origin.derived");
  }
}

/** One row per attribute in the snapshot, in ontology order. */
export function snapshotRows(
  snapshot: Snapshot,
  nodes: readonly ProfileNode[],
  ontology: Ontology,
): SnapshotRow[] {
  return Object.keys(snapshot.attributes)
    .sort(compareByOntologyOrder(ontology))
    .map((key) => {
      const origin = originOf(key, snapshot, nodes);
      return {
        key,
        label: attributeLabel(key),
        valueText: formatValue(attributeOf(ontology, key), snapshot.attributes[key]),
        origin,
        originLabel: originLabel(origin),
      };
    });
}
