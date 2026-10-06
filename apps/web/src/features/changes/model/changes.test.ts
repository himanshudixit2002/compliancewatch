import { describe, expect, it } from "vitest";
import { impactBusinessFromDto } from "@/entities/applicability/mappers";
import { ruleChangeFromDto } from "@/entities/change/mappers";
import type { ClauseDetail } from "@/entities/rulebook/types";
import { changeImpactDto, ruleChangeDto } from "@/test/change-fixture";
import { CLAUSE_ID, DOCUMENT_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import {
  applicabilityLabel,
  applicabilityOf,
  applicabilityView,
  changeCard,
  deadlineText,
  effectiveText,
  feedHrefs,
  kindLabel,
  kindTone,
  readFeedCursor,
  relationsText,
} from "./changes";

function businesses(...results: ("applies" | "not_applicable" | "unsure")[]) {
  return changeImpactDto(
    results.map((result, index) => ({
      result,
      businessId: `00000000-0000-4000-8000-0000000000a${index + 1}`,
    })),
  ).items[0]!.businesses.map(impactBusinessFromDto);
}

const CLAUSE: ClauseDetail = {
  clauseId: CLAUSE_ID,
  documentId: DOCUMENT_ID,
  clauseRef: "en.p2",
  ordinal: 2,
  page: 1,
  text: "Example whole clause text.",
  regulator: "Example regulator",
  docType: "circular",
  externalRef: "Example 1/2000",
  title: "Example document title",
  url: "https://example.com/example.pdf",
  language: "en",
  publishedAt: null,
};

describe("kinds", () => {
  it("names each kind of change with a tone", () => {
    expect(kindLabel("published")).toBe("Published");
    expect(kindLabel("deadline_changed")).toBe("Due date moved");
    expect(kindTone("withdrawn")).toBe("danger");
    expect(kindTone("superseded")).toBe("neutral");
  });
});

describe("applicability for this business", () => {
  it("applies when it applies to any node, is unsure when one is, else does not apply", () => {
    expect(applicabilityOf(businesses("not_applicable", "applies"))).toBe("applies");
    expect(applicabilityOf(businesses("not_applicable", "unsure"))).toBe("unsure");
    expect(applicabilityOf(businesses("not_applicable"))).toBe("not_applicable");
    expect(applicabilityOf([])).toBe("not_decided");
    expect(applicabilityOf(null)).toBe("not_decided");
    expect(applicabilityLabel("unknown")).toBe("Could not be read");
  });

  it("says node by node what the engine decided, or why it could not be read", () => {
    const view = applicabilityView({ state: "read", businesses: businesses("applies") }, (id) =>
      id === REGISTRATION_ID ? "29ABCDE1234F1Z5 (Example registration)" : id,
    );
    expect(view).toMatchObject({
      value: "applies",
      label: "Applies to this business",
      tone: "success",
    });
    expect(view.details).toEqual([
      "29ABCDE1234F1Z5 (Example registration): applies, decided on 5 Jan 2000",
    ]);
    const failed = applicabilityView(
      { state: "failed", message: "Example down", correlationId: "req-example-5" },
      (id) => id,
    );
    expect(failed).toMatchObject({
      value: "unknown",
      failure: { message: "Example down", correlationId: "req-example-5" },
    });
  });
});

describe("dates and relations", () => {
  it("words the version's dates, with the exclusive end as its last day", () => {
    expect(effectiveText({ effectiveFrom: "2000-01-01", effectiveTo: null })).toBe(
      "In force from 1 Jan 2000.",
    );
    expect(effectiveText({ effectiveFrom: "2000-01-01", effectiveTo: "2000-04-01" })).toBe(
      "In force from 1 Jan 2000 until 31 Mar 2000.",
    );
  });

  it("words a moved due date and the versions a change acts on", () => {
    expect(deadlineText({ deadline: null })).toBeNull();
    expect(
      deadlineText({
        deadline: { periodLabel: "2000-01", newDueOn: "2000-02-25", evidenceClauseId: null },
      }),
    ).toBe("Due date for the period 2000-01 moved to 25 Feb 2000.");
    expect(
      deadlineText({ deadline: { periodLabel: null, newDueOn: null, evidenceClauseId: null } }),
    ).toBe("Due date moved to no date.");
    const change = ruleChangeFromDto(
      ruleChangeDto({
        relations: {
          supersedes: ["a"],
          corrects: ["b", "c"],
          withdraws: ["d"],
          extends_deadline: [{ rule_version_id: "e", period_label: null, new_due_on: null }],
        },
      }),
    );
    expect(relationsText(change)).toEqual([
      "Replaces 1 earlier version or versions.",
      "Corrects 2 version or versions.",
      "Withdraws 1 version or versions.",
      "Moves the due date of 1 version or versions.",
    ]);
    expect(relationsText(ruleChangeFromDto(ruleChangeDto()))).toEqual([]);
  });
});

describe("changeCard", () => {
  it("words a change's card with its review state, approvers, citations and applicability", () => {
    const applicability = applicabilityView({ state: "read", businesses: [] }, (id) => id);
    const card = changeCard(ruleChangeFromDto(ruleChangeDto()), {
      clauses: new Map([[CLAUSE_ID, CLAUSE]]),
      applicability,
    });
    expect(card).toMatchObject({
      kindLabel: "Published",
      title: "Example rule 2",
      needsReview: true,
      publishedAt: "5 Jan 2000",
      effective: "In force from 1 Jan 2000.",
      deadline: null,
      changedAt: "5 Jan 2000, 10:00 am IST",
    });
    expect(card.approvedBy).toHaveLength(2);
    expect(card.citations[0]).toMatchObject({
      quote: "Example quoted clause text.",
      clauseText: "Example whole clause text.",
      sourceHref: "https://example.com/example.pdf",
    });
    expect(card.applicability.label).toBe("Not decided for this business");
    const reviewed = changeCard(
      ruleChangeFromDto(ruleChangeDto({ seed_status: "reviewed", published_at: null })),
      { clauses: new Map(), applicability },
    );
    expect(reviewed).toMatchObject({ needsReview: false, publishedAt: null });
    expect(reviewed.citations[0]?.clauseText).toBeNull();
  });
});

describe("the feed's pages", () => {
  it("reads a cursor the service could have written and links the pages", () => {
    expect(readFeedCursor("eyJrIjp7fX0")).toBe("eyJrIjp7fX0");
    expect(readFeedCursor(["eyJ", "x"])).toBe("eyJ");
    expect(readFeedCursor("not a cursor")).toBeNull();
    expect(readFeedCursor("")).toBeNull();
    expect(readFeedCursor("a".repeat(513))).toBeNull();
    expect(readFeedCursor(undefined)).toBeNull();
    expect(feedHrefs("/b/x/changes", null, "next")).toEqual({
      nextHref: "/b/x/changes?cursor=next",
      firstHref: null,
    });
    expect(feedHrefs("/b/x/changes", "now", null)).toEqual({
      nextHref: null,
      firstHref: "/b/x/changes",
    });
  });
});
