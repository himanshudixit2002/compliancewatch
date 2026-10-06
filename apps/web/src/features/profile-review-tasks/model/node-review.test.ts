import { describe, expect, it } from "vitest";
import {
  profileNodeFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
} from "@/entities/business/mappers";
import { attributeOf } from "@/entities/ontology/mappers";
import {
  ENTITY_ID,
  REGISTRATION_DTO,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TENANT_ID,
} from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { formatStoredValue, levelLabel, nodeReviewView, reasonLabel } from "./node-review";

const PATH = "/admin/profiles/review-tasks";

function view(ontology = ontologyFixture()) {
  return nodeReviewView({
    pathname: PATH,
    tenantId: TENANT_ID,
    fy: "2000-01",
    node: profileNodeFromDto(REGISTRATION_DTO),
    tasks: [
      reviewTaskFromDto({ ...REVIEW_TASK_DTO, id: "older", created_at: "1999-01-01T00:00:00Z" }),
      reviewTaskFromDto(REVIEW_TASK_DTO),
    ],
    snapshot: snapshotFromDto(SNAPSHOT_DTO),
    ontology,
  });
}

describe("nodeReviewView", () => {
  it("shows the node with a lookup of its parent, its tasks newest first and its snapshot", () => {
    const result = view();
    expect(result.node).toMatchObject({
      levelLabel: "Registration",
      name: "Example registration",
      parentId: ENTITY_ID,
      parentHref: `${PATH}?tenant=${TENANT_ID}&node=${ENTITY_ID}&fy=2000-01`,
    });
    expect(result.tasks.map((task) => task.id)).toEqual([REVIEW_TASK_DTO.id, "older"]);
    expect(result.tasks[0]).toMatchObject({
      attributeName: "Example definition of example_flag.",
      reasonLabel: "The business answered that it does not apply",
    });
    expect(result.snapshot.rows).toEqual([
      {
        key: "example_kind",
        name: "Example definition of example_kind.",
        value: "Example second kind",
      },
      {
        key: "state_codes",
        name: "Example definition of state_codes.",
        value: "Example place one, Example place two",
      },
      {
        key: "example_band",
        name: "Example definition of example_band.",
        value: "Example medium band",
      },
    ]);
    expect(result.ontologyMissing).toBe(false);
  });

  it("shows names and values as stored without the ontology", () => {
    const result = view(null as never);
    expect(result.ontologyMissing).toBe(true);
    expect(result.snapshot.rows.map((row) => row.key)).toEqual([
      "example_band",
      "example_kind",
      "state_codes",
    ]);
    expect(result.snapshot.rows[2]).toEqual({
      key: "state_codes",
      name: "State codes",
      value: '["01","02"]',
    });
  });
});

describe("the wording", () => {
  it("words levels and reasons, and one it does not know as sent", () => {
    expect(levelLabel("entity")).toBe("Legal entity");
    expect(levelLabel("example_level")).toBe("Example level");
    expect(reasonLabel("verify_registration")).toBe("No lookup could verify the registration");
    expect(reasonLabel("example_reason")).toBe("Example reason");
  });

  it("words a value by its attribute's type", () => {
    const ontology = ontologyFixture();
    const of = (key: string) => attributeOf(ontology, key);
    expect(formatStoredValue(of("example_flag"), true)).toBe("Yes");
    expect(formatStoredValue(of("example_flag"), false)).toBe("No");
    expect(formatStoredValue(of("example_count"), 1200)).toBe("1,200");
    expect(formatStoredValue(of("example_since"), "2000-01-15")).toBe("15 Jan 2000");
    expect(formatStoredValue(of("state_codes"), [])).toBe("None");
    expect(formatStoredValue(of("example_ratio"), "1.5")).toBe("1.5");
    expect(formatStoredValue(undefined, null)).toBe("No value");
    expect(formatStoredValue(undefined, 7)).toBe("7");
  });
});
