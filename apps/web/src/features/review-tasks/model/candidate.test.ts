import { describe, expect, it } from "vitest";
import { ruleCandidateFromDto } from "@/entities/rule-version/mappers";
import { ontologyFixture } from "@/test/ontology-fixture";
import { EXAMPLE_ANALYST_ID } from "@/test/rule-version-fixture";
import { ruleCandidateDto } from "@/test/review-task-fixture";
import { candidatePane, candidateStatusLabel, rejectReasonLabel } from "./candidate";

describe("candidatePane", () => {
  it("states the extraction, its issues, the suggested key and the proposed draft field by field", () => {
    const pane = candidatePane(
      ruleCandidateFromDto(ruleCandidateDto()),
      ontologyFixture(),
      EXAMPLE_ANALYST_ID,
    );
    expect(pane).toMatchObject({
      unparseable: false,
      outcome: "Extracted",
      confidence: "82%",
      model: "example/model",
      promptVersion: "example.extraction@1",
      needsReview: true,
      status: "Open",
      citationCount: 1,
      createdAt: "1 May 2000, 9:30 am IST",
      issues: [
        {
          code: "example_issue",
          clauseRef: "en.p2",
          detail: "Example detail of what the check found.",
        },
      ],
      highImpactSuggested: true,
      highImpactReasons: ["Example reason it looks high impact"],
      suggestedKey: "example_suggested_rule",
      suggestedKnown: false,
      decided: null,
      facts: [
        { label: "Source", value: "example_source" },
        { label: "Read as", value: "Circular" },
        { label: "Ontology version", value: "0.0.1" },
      ],
    });
    expect(pane.proposal).toMatchObject({
      title: "Example candidate title",
      summary: "Example summary the candidate proposes.",
      period: "From 1 Apr 2000, open-ended",
      recurrence: "Does not recur",
      template: {
        title: "Example obligation",
        steps: ["Example first step"],
        due: "Due 30 days after it applies",
        evidence: "None",
      },
      citations: [{ clauseRef: "en.p1", quote: "Example clause text that opens" }],
      problems: ["effective_to: Example problem the analyst fixes"],
    });
    expect(pane.proposal.specification).toMatchObject({
      kind: "group",
      items: [{ attribute: "example_kind", condition: "is Example second kind" }],
    });
  });

  it("says an unparseable candidate has nothing to propose, and who rejected one and why", () => {
    const pane = candidatePane(
      ruleCandidateFromDto(
        ruleCandidateDto({
          outcome: "unparseable",
          candidate: null,
          status: "rejected",
          reject_reason: "unparseable",
          decided_by: EXAMPLE_ANALYST_ID,
          decided_at: "2000-05-03T06:00:00Z",
          source_key: null,
          doc_type: null,
          ontology_version: null,
          proposed: {
            title: null,
            summary: null,
            specification: null,
            obligation_template: null,
            recurrence: { frequency: "annual", due_day: 31, due_month_offset: 2 },
            effective_from: null,
            effective_to: "2001-04-01",
            citations: [],
            problems: [],
          },
        }),
      ),
      null,
      EXAMPLE_ANALYST_ID,
    );
    expect(pane).toMatchObject({
      unparseable: true,
      outcome: "Unparseable",
      status: "Rejected",
      facts: [],
      decided: {
        by: { userId: EXAMPLE_ANALYST_ID, you: true },
        at: "3 May 2000, 11:30 am IST",
        reason: "Unparseable",
      },
      proposal: {
        title: null,
        specification: null,
        template: null,
        period: "From no start date until 1 Apr 2001 (the end day excluded)",
        recurrence: "Annual, due on day 31, 2 months after the month that follows the period",
      },
    });
  });

  it("words a status or reason it does not know as sent", () => {
    expect(candidateStatusLabel("drafted")).toBe("Drafted");
    expect(candidateStatusLabel("example_status")).toBe("Example status");
    expect(rejectReasonLabel("duplicate")).toBe("A duplicate of a rule");
    expect(rejectReasonLabel("example_reason")).toBe("Example reason");
  });
});
