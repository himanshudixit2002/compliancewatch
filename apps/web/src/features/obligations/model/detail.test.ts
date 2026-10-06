import { describe, expect, it } from "vitest";
import { decisionFromDto } from "@/entities/applicability/mappers";
import { obligationDetailFromDto } from "@/entities/obligation/mappers";
import type { ClauseDetail } from "@/entities/rulebook/types";
import {
  APPROVER_IDS,
  CLAUSE_ID,
  DECISION_ID,
  DOCUMENT_ID,
  NOW,
  USER_ID,
  changeDto,
  commentDto,
  decisionDto,
  obligationDetailDto,
  ruleVersionFactsDto,
} from "@/test/obligation-fixture";
import {
  actorText,
  assigneeText,
  citationViews,
  historyItems,
  memberLabel,
  obligationPageView,
  percent,
  reviewView,
  whyView,
} from "./detail";

const CLAUSE: ClauseDetail = {
  clauseId: CLAUSE_ID,
  documentId: DOCUMENT_ID,
  clauseRef: "en.p2",
  ordinal: 2,
  page: 1,
  text: "Example whole clause text, longer than the quote.",
  regulator: "Example regulator",
  docType: "circular",
  externalRef: "Example 1/2000",
  title: "Example document title",
  url: "https://example.com/example-document.pdf",
  language: "en",
  publishedAt: "2000-01-01",
};

const OTHER_USER = "00000000-0000-4000-8000-0000000000ac";

describe("citationViews", () => {
  it("joins each verified quote with its clause's text and source, when the clause was read", () => {
    const detail = obligationDetailFromDto(obligationDetailDto());
    const [read] = citationViews(detail, new Map([[CLAUSE_ID, CLAUSE]]));
    expect(read).toMatchObject({
      clauseRef: "en.p2",
      quote: "Example quoted clause text.",
      clauseText: "Example whole clause text, longer than the quote.",
      documentTitle: "Example document title",
      documentRef: "Example 1/2000",
      sourceHref: "https://example.com/example-document.pdf",
      page: 1,
      verifiedAt: "2 Jan 2000",
    });
    const [unread] = citationViews(detail, new Map());
    expect(unread).toMatchObject({ clauseText: null, documentTitle: null, sourceHref: null });
  });

  it("links only to an http or https source", () => {
    const detail = obligationDetailFromDto(obligationDetailDto());
    const [view] = citationViews(
      detail,
      new Map([[CLAUSE_ID, { ...CLAUSE, url: "javascript:alert(1)" }]]),
    );
    expect(view?.sourceHref).toBeNull();
  });
});

describe("whyView", () => {
  it("words the decision and each predicate, and notices a later decision", () => {
    const why = whyView(decisionFromDto(decisionDto({ confidence: 0.92 })), DECISION_ID);
    expect(why).toMatchObject({
      state: "decided",
      result: "Applies",
      tone: "success",
      confidence: "92%",
      later: false,
      needsReview: false,
      trigger: "Rule published",
      year: "1999-00",
    });
    expect(why.state === "decided" ? why.predicates : []).toEqual([
      {
        attribute: "example_kind",
        description: "Example kind is second",
        outcome: "Met",
        tone: "success",
        reason: "Example kind is second on this node",
        confidence: "100%",
        needsReview: false,
      },
    ]);
    const later = whyView(decisionFromDto(decisionDto({ result: "unsure" })), "another");
    expect(later).toMatchObject({ result: "Not sure", tone: "warning", later: true });
    expect(whyView(null, DECISION_ID)).toEqual({ state: "none" });
    expect(percent(0.456)).toBe("46%");
  });
});

describe("history and comments", () => {
  it("tells each change in words, with who made it", () => {
    const items = historyItems(
      obligationDetailFromDto(
        obligationDetailDto({
          history: [
            changeDto(),
            changeDto({
              change_id: "c2",
              kind: "started",
              status_after: "in_progress",
              actor: USER_ID,
            }),
            changeDto({
              change_id: "c3",
              kind: "assigned",
              new_assignee_id: OTHER_USER,
              actor: OTHER_USER,
            }),
            changeDto({ change_id: "c4", kind: "unassigned" }),
            changeDto({
              change_id: "c5",
              kind: "rescheduled",
              previous_due_at: "2000-01-20T18:29:59Z",
              new_due_at: "2000-01-25T18:29:59Z",
              reason: "deadline_extended",
            }),
            changeDto({ change_id: "c6", kind: "rescheduled" }),
            changeDto({
              change_id: "c7",
              kind: "closed",
              status_after: "waived",
              reason: "waived_by_user",
              note: "Example waiver reason",
              actor: USER_ID,
            }),
          ],
        }),
      ).history,
      USER_ID,
    );
    expect(items.map((item) => item.title)).toEqual([
      "Created",
      "Started",
      "Given to user 00000000",
      "Given to nobody",
      "Due date moved from 20 Jan 2000 to 25 Jan 2000",
      "Due date moved from No due date to No due date",
      "Closed: Waived",
    ]);
    expect(items[0]?.body).toBe("By the system");
    expect(items[1]?.body).toBe("By you");
    expect(items[2]?.body).toBe("By user 00000000");
    expect(items[6]?.body).toBe("By you. Waived by the business. Note: Example waiver reason");
    expect(items[6]?.tone).toBe("neutral");
    expect(actorText(null, USER_ID)).toBe("By the system");
  });
});

describe("reviewView", () => {
  it("names the approvers and the publication, and says when the rule is not reviewed", () => {
    const review = reviewView(obligationDetailFromDto(obligationDetailDto()));
    expect(review).toMatchObject({
      reviewed: false,
      label: "Not yet reviewed",
      ruleTitle: "Example rule 1",
      approvedBy: [...APPROVER_IDS],
      publishedAt: "2 Jan 2000",
      effective: "In force from 1 Jan 2000.",
    });
    const ended = reviewView(
      obligationDetailFromDto(
        obligationDetailDto({
          rule_version: ruleVersionFactsDto({
            effective_to: "2000-12-01",
            published_at: null,
            approved_by: [],
          }),
        }),
      ),
    );
    expect(ended).toMatchObject({
      effective: "In force from 1 Jan 2000 until 30 Nov 2000.",
      publishedAt: null,
      approvedBy: [],
    });
    expect(
      reviewView(obligationDetailFromDto(obligationDetailDto({ rule_version: null }))),
    ).toMatchObject({
      ruleTitle: null,
      effective: null,
      label: "Review not known yet",
    });
  });
});

describe("obligationPageView", () => {
  it("words the whole page and offers the changes its status allows", () => {
    const view = obligationPageView(
      obligationDetailFromDto(
        obligationDetailDto({
          comments: [
            commentDto(),
            commentDto({ comment_id: "c12", author_id: OTHER_USER, author_label: "ca_staff" }),
          ],
        }),
      ),
      {
        node: "29ABCDE1234F1Z5 (Example registration)",
        clauses: new Map(),
        why: { state: "none" },
        viewerId: USER_ID,
        now: NOW,
      },
    );
    expect(view).toMatchObject({
      title: "Example return 1",
      period: "Period 2000-01: 1 Jan 2000 to 31 Jan 2000",
      statusLabel: "Open",
      due: "20 Jan 2000",
      dueNote: "Due in 10 days",
      overdue: false,
      closed: null,
      evidence: "Example acknowledgement",
      open: true,
    });
    expect(view.actions.map((action) => action.label)).toEqual([
      "Start work",
      "Mark as done",
      "Waive",
    ]);
    expect(view.comments.map((comment) => comment.author)).toEqual(["You", "CA staff"]);
    const closed = obligationPageView(
      obligationDetailFromDto(
        obligationDetailDto({
          status: "done",
          closed_at: "2000-01-08T05:00:00Z",
          closed_reason: "completed",
        }),
      ),
      { node: "x", clauses: new Map(), why: { state: "none" }, viewerId: USER_ID, now: NOW },
    );
    expect(closed).toMatchObject({ open: false, actions: [], closed: "Completed on 8 Jan 2000" });
  });
});

describe("assignees", () => {
  it("say who an obligation is given to and list members with their roles", () => {
    const members = [{ id: OTHER_USER, name: "Example colleague", roles: ["staff"] }];
    expect(assigneeText(null, USER_ID)).toBe("Nobody");
    expect(assigneeText(USER_ID, USER_ID)).toBe("You");
    expect(assigneeText(OTHER_USER, USER_ID, members)).toBe("Example colleague");
    expect(assigneeText(OTHER_USER, USER_ID)).toBe(`User ${OTHER_USER}`);
    expect(memberLabel(members[0]!)).toBe("Example colleague (Staff)");
    expect(memberLabel({ id: OTHER_USER, name: "Example colleague", roles: [] })).toBe(
      "Example colleague",
    );
  });
});
