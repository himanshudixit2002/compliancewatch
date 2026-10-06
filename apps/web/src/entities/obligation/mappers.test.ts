import { describe, expect, it } from "vitest";
import {
  APPROVER_IDS,
  CLAUSE_ID,
  OBLIGATION_ID,
  REGISTRATION_ID,
  changeDto,
  commentDto,
  dueAt,
  listedObligationDto,
  obligationDetailDto,
  obligationPageDto,
} from "@/test/obligation-fixture";
import {
  listedObligationFromDto,
  obligationDetailFromDto,
  obligationPageFromDto,
  statusChangeToDto,
} from "./mappers";

describe("obligation mappers", () => {
  it("map a listed obligation with its rule's facts and its citations", () => {
    const listed = listedObligationFromDto(listedObligationDto());
    expect(listed).toMatchObject({
      id: OBLIGATION_ID,
      businessId: REGISTRATION_ID,
      title: "Example return 1",
      steps: ["Example step one", "Example step two"],
      periodLabel: "2000-01",
      periodStart: "2000-01-01",
      periodEnd: "2000-02-01",
      dueAt: dueAt("2000-01-20"),
      status: "open",
      assigneeId: null,
    });
    expect(listed.ruleVersion).toMatchObject({
      title: "Example rule 1",
      seedStatus: "needs_review",
      reviewed: false,
      approvedBy: [...APPROVER_IDS],
      publishedAt: "2000-01-02T04:30:00Z",
    });
    expect(listed.citations).toEqual([
      expect.objectContaining({ clauseId: CLAUSE_ID, clauseRef: "en.p2", matchScore: 1 }),
    ]);
  });

  it("keep a missing rule version as null and the page's cursor", () => {
    const page = obligationPageFromDto(
      obligationPageDto([listedObligationDto({ rule_version: null, citations: [] })], "next-1"),
    );
    expect(page.items[0]?.ruleVersion).toBeNull();
    expect(page.items[0]?.citations).toEqual([]);
    expect(page.nextCursor).toBe("next-1");
  });

  it("map the detail's history and comments in their order", () => {
    const detail = obligationDetailFromDto(
      obligationDetailDto({
        history: [
          changeDto(),
          changeDto({
            change_id: "00000000-0000-4000-8000-000000000c02",
            kind: "closed",
            status_after: "waived",
            reason: "waived_by_user",
            note: "Example waiver reason",
            actor: "00000000-0000-4000-8000-0000000000ab",
          }),
        ],
        comments: [commentDto()],
      }),
    );
    expect(detail.history.map((change) => change.kind)).toEqual(["created", "closed"]);
    expect(detail.history[1]).toMatchObject({
      statusAfter: "waived",
      note: "Example waiver reason",
      actor: "00000000-0000-4000-8000-0000000000ab",
    });
    expect(detail.comments[0]).toMatchObject({ body: "Example comment", authorLabel: "owner" });
  });

  it("send a reason with a waiver only, trimmed", () => {
    expect(statusChangeToDto({ action: "start", reason: "ignored" })).toEqual({ action: "start" });
    expect(statusChangeToDto({ action: "complete", reason: "" })).toEqual({ action: "complete" });
    expect(statusChangeToDto({ action: "waive", reason: "  Example waiver reason  " })).toEqual({
      action: "waive",
      reason: "Example waiver reason",
    });
  });
});
