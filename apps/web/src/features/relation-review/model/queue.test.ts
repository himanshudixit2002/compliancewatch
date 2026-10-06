import { describe, expect, it } from "vitest";
import { relationCandidateFromDto } from "@/entities/rulebook/mappers";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_DOCUMENT_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import {
  CANDIDATE_PAGE_SIZE,
  candidateHref,
  candidateQueueHref,
  candidateQueueView,
  candidateRow,
  candidateStatusLabel,
  percent,
  periodText,
  readCandidateQueue,
  statusChips,
} from "./queue";

const PATH = "/admin/rulebook/relations";

function candidates(count: number) {
  return Array.from({ length: count }, (_, index) =>
    relationCandidateFromDto(
      relationCandidateDto({
        candidate_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      }),
    ),
  );
}

describe("readCandidateQueue", () => {
  it("lists the open candidates of every document by default", () => {
    expect(readCandidateQueue({})).toEqual({
      kind: "ok",
      filter: { status: "open", documentId: null, after: null },
    });
  });

  it("reads a status, a document and a cursor, and reads an unknown status as open", () => {
    expect(
      readCandidateQueue({
        status: "rejected",
        document: EXAMPLE_DOCUMENT_ID.toUpperCase(),
        after: EXAMPLE_CANDIDATE_ID,
      }),
    ).toEqual({
      kind: "ok",
      filter: { status: "rejected", documentId: EXAMPLE_DOCUMENT_ID, after: EXAMPLE_CANDIDATE_ID },
    });
    expect(readCandidateQueue({ status: "example", after: "not-an-id" })).toEqual({
      kind: "ok",
      filter: { status: "open", documentId: null, after: null },
    });
  });

  it("refuses a malformed document id and reads nothing", () => {
    expect(readCandidateQueue({ status: "approved", document: "not-a-document" })).toEqual({
      kind: "invalid",
      value: "not-a-document",
      filter: { status: "approved", documentId: null, after: null },
    });
  });
});

describe("the queue's links", () => {
  it("leave the default status out and keep the document across the chips", () => {
    expect(candidateQueueHref(PATH, { status: "open", documentId: null, after: null })).toBe(PATH);
    const chips = statusChips(PATH, {
      status: "approved",
      documentId: EXAMPLE_DOCUMENT_ID,
      after: EXAMPLE_CANDIDATE_ID,
    });
    expect(chips.map((chip) => [chip.label, chip.href, chip.current])).toEqual([
      ["Open", `${PATH}?document=${EXAMPLE_DOCUMENT_ID}`, false],
      ["Approved", `${PATH}?status=approved&document=${EXAMPLE_DOCUMENT_ID}`, true],
      ["Rejected", `${PATH}?status=rejected&document=${EXAMPLE_DOCUMENT_ID}`, false],
    ]);
    expect(candidateHref(EXAMPLE_CANDIDATE_ID, "rejected")).toBe(
      `${PATH}/${EXAMPLE_CANDIDATE_ID}?status=rejected`,
    );
    expect(candidateHref(EXAMPLE_CANDIDATE_ID, "example")).toBe(`${PATH}/${EXAMPLE_CANDIDATE_ID}`);
  });
});

describe("the queue's words", () => {
  it("reads shares as whole percentages and a status it does not know as sent", () => {
    expect(percent(0.875)).toBe("88%");
    expect(percent(1.2)).toBe("100%");
    expect(percent(-1)).toBe("0%");
    expect(candidateStatusLabel("example_status")).toBe("Example status");
  });

  it("words a deadline's period and new due date", () => {
    expect(periodText({ periodLabel: "2000-01", newDueOn: "2000-02-21" })).toBe(
      "Period 2000-01, new due date 21 Feb 2000",
    );
    expect(periodText({ periodLabel: null, newDueOn: "2000-02-21" })).toBe(
      "New due date 21 Feb 2000",
    );
    expect(periodText({ periodLabel: "2000-01", newDueOn: null })).toBe("2000-01");
    expect(periodText({ periodLabel: null, newDueOn: null })).toBeNull();
  });

  it("shows a candidate with its target, evidence link, scores and flags", () => {
    expect(candidateRow(relationCandidateFromDto(relationCandidateDto()))).toEqual({
      candidateId: EXAMPLE_CANDIDATE_ID,
      href: `${PATH}/${EXAMPLE_CANDIDATE_ID}?status=open`,
      relationLabel: "Extends deadline",
      targetLabel: "Form",
      targetName: "EXAMPLE-1",
      aligned: false,
      targetRuleKey: "example_rule",
      evidenceQuote: "clause text that opens",
      evidenceHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=00000000-0000-5000-8000-0000000000c1`,
      quoteScore: "100%",
      confidence: "90%",
      needsReview: true,
      issues: ["Target unaligned"],
      period: "Period 2000-01, new due date 21 Feb 2000",
      status: "open",
      statusLabel: "Open",
    });
  });
});

describe("candidateQueueView", () => {
  it("shows a page and continues after its last candidate", () => {
    const view = candidateQueueView(
      PATH,
      { status: "open", documentId: null, after: null },
      candidates(CANDIDATE_PAGE_SIZE + 1),
    );
    expect(view.rows).toHaveLength(CANDIDATE_PAGE_SIZE);
    expect(view.nextHref).toBe(
      `${PATH}?after=00000000-0000-4000-8000-${String(CANDIDATE_PAGE_SIZE).padStart(12, "0")}`,
    );
    expect(view.firstHref).toBeNull();
  });

  it("links back to the first page from a later one", () => {
    const view = candidateQueueView(
      PATH,
      { status: "rejected", documentId: null, after: EXAMPLE_CANDIDATE_ID },
      candidates(1),
    );
    expect(view.nextHref).toBeNull();
    expect(view.firstHref).toBe(`${PATH}?status=rejected`);
  });
});
