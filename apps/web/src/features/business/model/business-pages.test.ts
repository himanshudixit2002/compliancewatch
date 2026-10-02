import { describe, expect, it } from "vitest";
import {
  businessFromDto,
  onboardingFromDto,
  profileNodeFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
} from "@/entities/business/mappers";
import {
  BUSINESS_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  LOCATION_DTO,
  LOCATION_ID,
  ONBOARDING_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
} from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import {
  attributesView,
  businessHeader,
  businessHomeView,
  financialYearChoices,
  resolveNode,
  reviewTasksView,
  selectedFinancialYear,
  snapshotView,
  type AttributesInput,
  type ResolvedNode,
} from "./business-pages";

const BUSINESS = businessFromDto(BUSINESS_DTO);
const LOCATION = profileNodeFromDto(LOCATION_DTO);
const ONTOLOGY = ontologyFixture();
const NOW = new Date("2026-09-29T06:00:00Z");

function resolved(nodeId?: string, location?: typeof LOCATION): ResolvedNode {
  const found = resolveNode(BUSINESS, nodeId, location);
  if (found === null) throw new Error("not resolved");
  return found;
}

function input(overrides: Partial<AttributesInput> = {}): AttributesInput {
  return {
    business: BUSINESS,
    resolved: resolved(REGISTRATION_ID),
    ontology: ONTOLOGY,
    fy: "2000-01",
    canEdit: true,
    editHref: (key) => `/edit/${key}`,
    now: NOW,
    ...overrides,
  };
}

describe("resolveNode", () => {
  it("finds the business, a registration, or a location under one", () => {
    expect(resolved().node.id).toBe(ENTITY_ID);
    expect(resolved(ENTITY_ID).ancestors).toEqual([]);
    const registration = resolved(REGISTRATION_ID);
    expect(registration.node.level).toBe("registration");
    expect(registration.ancestors.map((node) => node.id)).toEqual([ENTITY_ID]);
    const location = resolved(LOCATION_ID, LOCATION);
    expect(location.ancestors.map((node) => node.id)).toEqual([ENTITY_ID, REGISTRATION_ID]);
  });

  it("refuses a node that is not part of the business", () => {
    expect(resolveNode(BUSINESS, LOCATION_ID)).toBeNull();
    expect(resolveNode(BUSINESS, LOCATION_ID, { ...LOCATION, id: "other" })).toBeNull();
    expect(resolveNode(BUSINESS, LOCATION_ID, { ...LOCATION, level: "registration" })).toBeNull();
    expect(resolveNode(BUSINESS, LOCATION_ID, { ...LOCATION, parentId: "elsewhere" })).toBeNull();
  });
});

describe("financial years", () => {
  it("offers this year and the two before, and keeps an older one asked for", () => {
    expect(financialYearChoices("2026-27", NOW)).toEqual(["2026-27", "2025-26", "2024-25"]);
    expect(financialYearChoices("2000-01", NOW)).toEqual([
      "2026-27",
      "2025-26",
      "2024-25",
      "2000-01",
    ]);
  });

  it("takes a well-formed year from the query, else the current one", () => {
    expect(selectedFinancialYear("2025-26", NOW)).toBe("2025-26");
    expect(selectedFinancialYear("2025-27", NOW)).toBe("2026-27");
    expect(selectedFinancialYear(undefined, NOW)).toBe("2026-27");
  });
});

describe("businessHeader and businessHomeView", () => {
  it("names the business, its registrations and its state across the nodes", () => {
    const header = businessHeader(BUSINESS);
    expect(header).toMatchObject({ id: ENTITY_ID, name: "Example business", pan: "ABCDE1234F" });
    expect(header.updatedAt).toMatch(/IST$/);
    expect(header.registrations).toEqual([
      {
        id: REGISTRATION_ID,
        level: "registration",
        key: DEMO_GSTIN,
        name: "Example registration",
        levelLabel: "Registration (GSTIN)",
        display: `${DEMO_GSTIN} (Example registration)`,
        version: 3,
      },
    ]);
    const home = businessHomeView(BUSINESS, onboardingFromDto(ONBOARDING_DTO), [
      reviewTaskFromDto(REVIEW_TASK_DTO),
      reviewTaskFromDto({ ...REVIEW_TASK_DTO, id: "closed", open: false }),
    ]);
    expect(home.counts).toEqual({ known: 3, unsure: 1, not_applicable: 1 });
    expect(home.openTasks).toBe(1);
    expect(home.progress.text).toBe("4 of 8 answered");
  });
});

describe("attributesView", () => {
  it("lists a registration's own values, the business's inherited ones and what is missing", () => {
    const view = attributesView(input());
    expect(view.node).toMatchObject({ id: REGISTRATION_ID, level: "registration" });
    expect(view.nodes.map((node) => node.id)).toEqual([ENTITY_ID, REGISTRATION_ID]);
    expect(view.own.map((row) => [row.key, row.editHref])).toEqual([
      ["example_kind", "/edit/example_kind"],
      ["example_flag", "/edit/example_flag"],
    ]);
    expect(view.inherited.map((row) => [row.key, row.fromName])).toEqual([
      ["state_codes", "Example business (PAN ABCDE1234F)"],
      ["example_band", "Example business (PAN ABCDE1234F)"],
      ["example_count", "Example business (PAN ABCDE1234F)"],
    ]);
    expect(view.unanswered).toEqual([
      { key: "example_since", label: "Example since", editHref: "/edit/example_since" },
    ]);
    expect(view.fyChoices).toContain("2000-01");
    expect(view.editing).toBeNull();
    expect(view.canEdit).toBe(true);
  });

  it("shows a per-year value only for its year and asks for it in another", () => {
    const view = attributesView(input({ resolved: resolved(), fy: "2001-02" }));
    expect(view.own.map((row) => row.key)).toEqual(["state_codes", "example_count"]);
    expect(view.inherited).toEqual([]);
    expect(view.unanswered.map((item) => item.key)).toEqual(["example_band"]);
  });

  it("opens the edit form for an attribute of the node's level, with its stored value", () => {
    const kind = attributesView(input({ edit: "example_kind" })).editing;
    expect(kind).toMatchObject({
      key: "example_kind",
      label: "Example kind",
      question: "Example question about example_kind?",
      asOfFy: null,
      defaultValue: "second",
    });
    const band = attributesView(input({ resolved: resolved(), edit: "example_band" })).editing;
    expect(band?.asOfFy).toBe("2000-01");
    expect(band?.defaultValue).toBe("medium");
    expect(attributesView(input({ edit: "example_flag" })).editing?.defaultValue).toBeUndefined();
  });

  it("opens no form for another level, a derived or unknown attribute, or a reader", () => {
    expect(attributesView(input({ edit: "state_codes" })).editing).toBeNull();
    expect(
      attributesView(input({ resolved: resolved(), edit: "example_derived" })).editing,
    ).toBeNull();
    expect(attributesView(input({ edit: "no_such_key" })).editing).toBeNull();
    const reader = attributesView(input({ canEdit: false, edit: "example_kind" }));
    expect(reader.editing).toBeNull();
    expect(reader.own.every((row) => row.editHref === null)).toBe(true);
    expect(reader.unanswered.every((item) => item.editHref === null)).toBe(true);
  });

  it("adds a location being shown to the nodes, inheriting from both ancestors", () => {
    const view = attributesView(input({ resolved: resolved(LOCATION_ID, LOCATION) }));
    expect(view.nodes.map((node) => node.id)).toEqual([ENTITY_ID, REGISTRATION_ID, LOCATION_ID]);
    expect(view.node.levelLabel).toBe("Location");
    expect(view.own).toEqual([]);
    expect(view.inherited.map((row) => row.fromName)).toEqual([
      "29ABCDE1234F1Z5 (Example registration)",
      "29ABCDE1234F1Z5 (Example registration)",
      "Example business (PAN ABCDE1234F)",
      "Example business (PAN ABCDE1234F)",
      "Example business (PAN ABCDE1234F)",
    ]);
    expect(view.unanswered.map((item) => item.key)).toEqual(["example_ratio", "example_note"]);
  });
});

describe("snapshotView and reviewTasksView", () => {
  it("words the snapshot with the origin of each value", () => {
    const view = snapshotView(
      BUSINESS,
      resolved(REGISTRATION_ID),
      snapshotFromDto(SNAPSHOT_DTO),
      ONTOLOGY,
      "2000-01",
      NOW,
    );
    expect(view.version).toBe(8);
    expect(view.rows.map((row) => [row.key, row.originLabel])).toEqual([
      ["example_kind", "Stored on this node"],
      ["state_codes", "Inherited from Example business (PAN ABCDE1234F)"],
      ["example_band", "Inherited from Example business (PAN ABCDE1234F)"],
    ]);
    const atLocation = snapshotView(
      BUSINESS,
      resolved(LOCATION_ID, LOCATION),
      snapshotFromDto(SNAPSHOT_DTO),
      ONTOLOGY,
      "2000-01",
    );
    expect(atLocation.nodes).toHaveLength(3);
  });

  it("lists every task with its node, and counts the open ones", () => {
    const view = reviewTasksView(BUSINESS, [
      reviewTaskFromDto(REVIEW_TASK_DTO),
      reviewTaskFromDto({ ...REVIEW_TASK_DTO, id: "closed", open: false }),
    ]);
    expect(view.openCount).toBe(1);
    expect(view.rows.map((row) => [row.id, row.nodeName])).toEqual([
      [REVIEW_TASK_DTO.id, "29ABCDE1234F1Z5 (Example registration)"],
      ["closed", "29ABCDE1234F1Z5 (Example registration)"],
    ]);
  });
});
