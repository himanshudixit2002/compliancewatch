import { describe, expect, it } from "vitest";
import { EXAMPLE_OTHER_VERSION_ID, EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { parseApproval, parseRejection } from "./decision-form";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

describe("parseApproval", () => {
  it("reads the draft, the affected version and a trimmed note", () => {
    expect(
      parseApproval(
        form({
          from_rule_version_id: ` ${EXAMPLE_VERSION_ID.toUpperCase()} `,
          target_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
          note: "  Example note ",
        }),
        true,
      ),
    ).toEqual({
      ok: true,
      approval: {
        fromRuleVersionId: EXAMPLE_VERSION_ID,
        targetRuleVersionId: EXAMPLE_OTHER_VERSION_ID,
        note: "Example note",
      },
    });
    expect(parseApproval(form({ from_rule_version_id: EXAMPLE_VERSION_ID }), false)).toEqual({
      ok: true,
      approval: { fromRuleVersionId: EXAMPLE_VERSION_ID, note: "" },
    });
  });

  it("asks for the draft, the affected version where one is needed, and a short note", () => {
    expect(parseApproval(form({ note: "x".repeat(2001) }), true)).toEqual({
      ok: false,
      errors: {
        note: ["A note has at most 2000 characters."],
        from_rule_version_id: ["Choose the draft the relation starts from."],
        target_rule_version_id: ["Choose the version this relation points at."],
      },
    });
    expect(
      parseApproval(
        form({ from_rule_version_id: EXAMPLE_VERSION_ID, target_rule_version_id: "x" }),
        false,
      ),
    ).toEqual({
      ok: false,
      errors: { target_rule_version_id: ["This is not a rule version's id."] },
    });
  });
});

describe("parseRejection", () => {
  it("reads one of the rulebook's reasons with a note", () => {
    expect(parseRejection(form({ reason: "duplicate", note: " Example " }))).toEqual({
      ok: true,
      rejection: { reason: "duplicate", note: "Example" },
    });
  });

  it("asks for a reason", () => {
    expect(parseRejection(form({ reason: "example" }))).toEqual({
      ok: false,
      errors: { reason: ["Choose why the candidate is rejected."] },
    });
  });
});
