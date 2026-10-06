import { describe, expect, it } from "vitest";
import { CHANGED_VERSION_ID, ruleChangeDto, ruleChangePageDto } from "@/test/change-fixture";
import { APPROVER_IDS, CLAUSE_ID } from "@/test/obligation-fixture";
import { ruleChangeFromDto, ruleChangePageFromDto } from "./mappers";

describe("change mappers", () => {
  it("map a published change with its citations and approvers", () => {
    const change = ruleChangeFromDto(ruleChangeDto());
    expect(change).toMatchObject({
      kind: "published",
      ruleVersionId: CHANGED_VERSION_ID,
      title: "Example rule 2",
      seedStatus: "needs_review",
      approvedBy: [...APPROVER_IDS],
      effectiveTo: null,
      deadline: null,
    });
    expect(change.citations).toEqual([
      {
        clauseId: CLAUSE_ID,
        documentId: expect.any(String),
        clauseRef: "en.p2",
        quote: "Example quoted clause text.",
      },
    ]);
  });

  it("map a deadline change and the versions a change acts on", () => {
    const change = ruleChangeFromDto(
      ruleChangeDto({
        kind: "deadline_changed",
        deadline: { period_label: "2000-01", new_due_on: "2000-02-25", evidence_clause_id: null },
        relations: {
          supersedes: ["00000000-0000-4000-8000-00000000c0d0"],
          corrects: [],
          withdraws: [],
          extends_deadline: [
            {
              rule_version_id: "00000000-0000-4000-8000-00000000c0d0",
              period_label: "2000-01",
              new_due_on: "2000-02-25",
            },
          ],
        },
      }),
    );
    expect(change.deadline).toEqual({
      periodLabel: "2000-01",
      newDueOn: "2000-02-25",
      evidenceClauseId: null,
    });
    expect(change.relations.supersedes).toHaveLength(1);
    expect(change.relations.extendsDeadline[0]?.newDueOn).toBe("2000-02-25");
  });

  it("keep the page's cursor", () => {
    expect(ruleChangePageFromDto(ruleChangePageDto([ruleChangeDto()], "next")).nextCursor).toBe(
      "next",
    );
  });
});
