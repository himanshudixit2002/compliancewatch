import { describe, expect, it } from "vitest";
import { ruleCandidateFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { ontologyFixture } from "@/test/ontology-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { ruleCandidateDto } from "@/test/review-task-fixture";
import { compare, proposalContent, versionContent } from "./diff";

const WORDS = { title: "Example comparison", beforeLabel: "Before", afterLabel: "After" };

describe("compare", () => {
  it("reads a long field that is the same on both sides as the same, past the table limit", () => {
    // 501 sentences a side: more cells than the diff aligns, yet nothing changed.
    const summary = Array.from({ length: 501 }, (_, n) => `Example sentence ${n}.`).join(" ");
    const version = ruleVersionFromDto(ruleVersionDto({ summary }));
    const comparison = compare(versionContent(version), versionContent(version), null, WORDS);
    expect(comparison.changed).toEqual([]);
    expect(comparison.same).toContain("Summary");
  });

  it("lists each changed field as lines, and the fields that read the same", () => {
    const before = versionContent(ruleVersionFromDto(ruleVersionDto()));
    const after = versionContent(
      ruleVersionFromDto(
        ruleVersionDto({
          summary: "Example summary of what the rule asks. Example second sentence.",
          effective_to: "2001-04-01",
          todo: [],
          obligation_template: {
            title: "Example obligation",
            steps: ["Example first step", "Example changed step"],
            due_in_days: null,
            evidence_type: "example_evidence",
          },
          specification: {
            all_of: [{ attribute: "example_kind", operator: "eq", value: "second" }],
          },
        }),
      ),
    );
    const comparison = compare(before, after, ontologyFixture(), WORDS);
    expect(comparison.title).toBe("Example comparison");
    expect(comparison.same).toEqual(["Title", "Recurrence"]);
    const byField = Object.fromEntries(comparison.changed.map((field) => [field.field, field]));
    expect(byField.summary?.lines).toEqual([
      { kind: "same", text: "Example summary of what the rule asks." },
      { kind: "added", text: "Example second sentence." },
    ]);
    expect(byField.period?.lines).toEqual([
      { kind: "same", text: "From: 1 Apr 2000" },
      { kind: "removed", text: "Until: open-ended" },
      { kind: "added", text: "Until: 1 Apr 2001" },
    ]);
    expect(byField.template?.lines).toContainEqual({
      kind: "added",
      text: "Step 2: Example changed step",
    });
    expect(byField.todo?.lines).toEqual([
      { kind: "removed", text: "Example question for the analyst?" },
    ]);
    expect(byField.specification?.lines).toContainEqual({
      kind: "added",
      text: "  example_kind is Example second kind",
    });
  });

  it("leaves out the questions a proposal does not state, and words what it leaves empty", () => {
    const proposal = proposalContent(
      ruleCandidateFromDto(
        ruleCandidateDto({
          proposed: {
            ...ruleCandidateDto().proposed,
            title: null,
            specification: null,
            obligation_template: null,
          },
        }),
      ).proposed,
    );
    const draft = versionContent(ruleVersionFromDto(ruleVersionDto()));
    const comparison = compare(proposal, draft, null, WORDS);
    const fields = comparison.changed.map((field) => field.field);
    expect(fields).not.toContain("todo");
    expect(comparison.same).not.toContain("Open questions");
    const title = comparison.changed.find((field) => field.field === "title");
    expect(title?.lines).toEqual([
      { kind: "removed", text: "Not stated" },
      { kind: "added", text: "Example rule title" },
    ]);
    const template = comparison.changed.find((field) => field.field === "template");
    expect(template?.lines[0]).toEqual({ kind: "removed", text: "Not stated" });
  });
});
