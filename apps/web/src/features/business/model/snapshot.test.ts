import { describe, expect, it } from "vitest";
import { businessFromDto, profileNodeFromDto, snapshotFromDto } from "@/entities/business/mappers";
import type { ProfileNode } from "@/entities/business/types";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_DTO, SNAPSHOT_DTO } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { originLabel, originOf, snapshotRows } from "./snapshot";

const ontology = ontologyFixture();
const business = businessFromDto(BUSINESS_DTO);
const entity: ProfileNode = {
  id: ENTITY_ID,
  level: "entity",
  key: business.pan,
  name: business.name,
  parentId: null,
  version: business.version,
  attributes: business.attributes,
  created: false,
};
const registration = profileNodeFromDto(REGISTRATION_DTO);
const snapshot = snapshotFromDto(SNAPSHOT_DTO);

describe("snapshotRows", () => {
  it("words each value and says which node supplies it, the nearest one winning", () => {
    const rows = snapshotRows(snapshot, [entity, registration], ontology);
    expect(rows.map((row) => [row.key, row.valueText, row.originLabel])).toEqual([
      ["example_kind", "Example second kind", "Stored on this node"],
      ["state_codes", "Example place one, Example place two", "Inherited from Example business"],
      ["example_band", "Example medium band", "Inherited from Example business"],
    ]);
  });

  it("lets the child win when both hold a value", () => {
    const own: ProfileNode = {
      ...registration,
      attributes: [
        ...registration.attributes,
        {
          key: "state_codes",
          state: "known",
          value: ["02"],
          asOfFy: null,
          source: "user_input",
          updatedAt: null,
        },
      ],
    };
    expect(originOf("state_codes", snapshot, [entity, own])).toEqual({ kind: "self" });
  });

  it("reads a per-year value for the snapshot's year only, and calls the rest derived", () => {
    const later = { ...snapshot, asOfFy: "2001-02" };
    expect(originOf("example_band", later, [entity, registration])).toEqual({ kind: "derived" });
    expect(originOf("example_count", snapshot, [entity, registration])).toEqual({
      kind: "derived",
    });
    // A lineage node the caller did not load is skipped.
    expect(originOf("state_codes", snapshot, [registration])).toEqual({ kind: "derived" });
    expect(originLabel({ kind: "derived" })).toBe("Worked out by the service");
    expect(originLabel({ kind: "inherited", nodeId: ENTITY_ID, nodeName: "Example" })).toBe(
      "Inherited from Example",
    );
  });
});
