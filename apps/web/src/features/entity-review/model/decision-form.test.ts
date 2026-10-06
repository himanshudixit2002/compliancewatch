import { describe, expect, it } from "vitest";
import { EXAMPLE_ENTITY_ID, EXAMPLE_REVIEW_IDS } from "@/test/rulebook-fixture";
import { DECISION_FIELDS } from "../ui/decision-shared";
import { parseDecision } from "./decision-form";

function form(values: Record<string, string | readonly string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (typeof value === "string") data.set(key, value);
    else for (const one of value) data.append(key, one);
  }
  return data;
}

describe("parseDecision", () => {
  it("reads a decision over the whole group with a trimmed note", () => {
    expect(parseDecision(form({ decision: "create_entity", note: "  Example note  " }))).toEqual({
      ok: true,
      decision: "create_entity",
      note: "Example note",
    });
  });

  it("keeps the entity for add_alias, the reason for reject and the included mentions once each", () => {
    expect(
      parseDecision(
        form({
          decision: "add_alias",
          entity_id: ` ${EXAMPLE_ENTITY_ID.toUpperCase()} `,
          reject_reason: "wrong_type",
          review_ids: [EXAMPLE_REVIEW_IDS.first, EXAMPLE_REVIEW_IDS.first, ""],
        }),
      ),
    ).toEqual({
      ok: true,
      decision: "add_alias",
      entityId: EXAMPLE_ENTITY_ID,
      reviewIds: [EXAMPLE_REVIEW_IDS.first],
      note: "",
    });
    expect(parseDecision(form({ decision: "reject", reject_reason: "wrong_type" }))).toEqual({
      ok: true,
      decision: "reject",
      rejectReason: "wrong_type",
      note: "",
    });
  });

  it("names each field the form got wrong, as the rulebook's body fields", () => {
    expect(parseDecision(form({}))).toEqual({
      ok: false,
      errors: { [DECISION_FIELDS.decision]: ["Choose a decision."] },
    });
    expect(
      parseDecision(
        form({
          decision: "add_alias",
          entity_id: "not-an-id",
          note: "x".repeat(2001),
          review_ids: ["not-an-id"],
        }),
      ),
    ).toEqual({
      ok: false,
      errors: {
        entity_id: ["Give the entity's id (a UUID)."],
        note: ["A note has at most 2000 characters."],
        review_ids: ["A decision names at most 200 mentions, each by its review id."],
      },
    });
    expect(parseDecision(form({ decision: "reject" }))).toEqual({
      ok: false,
      errors: { reject_reason: ["Choose why the mentions are rejected."] },
    });
    const many = Array.from(
      { length: 201 },
      (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    );
    expect(
      parseDecision(form({ decision: "reject", reject_reason: "wrong_type", review_ids: many })),
    ).toMatchObject({ ok: false, errors: { review_ids: [expect.any(String)] } });
  });

  it("asks a group whose name cannot name an entity for its mentions, and refuses to make one", () => {
    expect(parseDecision(form({ decision: "create_entity" }), false)).toEqual({
      ok: false,
      errors: {
        decision: ["This name cannot name an entity: add it to an entity or reject it."],
        review_ids: [
          "Include the mentions you decide: this name does not name one entity across documents.",
        ],
      },
    });
    expect(
      parseDecision(
        form({
          decision: "reject",
          reject_reason: "text_artifact",
          review_ids: [EXAMPLE_REVIEW_IDS.second],
        }),
        false,
      ),
    ).toMatchObject({ ok: true, reviewIds: [EXAMPLE_REVIEW_IDS.second] });
  });
});
