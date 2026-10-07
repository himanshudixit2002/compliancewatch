import { describe, expect, it } from "vitest";
import { relationCandidateFromDto, documentFromDto } from "@/entities/rulebook/mappers";
import { reviewTaskDetailFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { ReviewTaskDetailDto } from "@/entities/rule-version/types";
import { err, ok, webError } from "@/server/result";
import { ontologyFixture } from "@/test/ontology-fixture";
import {
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  documentDto,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  EXAMPLE_CANDIDATE_TASK_ID,
  EXAMPLE_RELATION_CANDIDATE_ID,
  EXAMPLE_REVIEWER_ID,
  EXAMPLE_TASK_ID,
  candidateTaskDetailDto,
  reviewTaskDetailDto,
  reviewTaskDto,
  ruleCandidateDto,
} from "@/test/review-task-fixture";
import { relationField, type RelationChoice } from "../ui/form-shared";
import {
  checkRelations,
  editorOntology,
  previousVersion,
  sourceDocumentIds,
  workbenchView,
  type Session,
  type WorkbenchReads,
} from "./workbench";

const ANALYST: Session = { userId: EXAMPLE_ANALYST_ID, roles: ["analyst"] };
const REVIEWER: Session = { userId: EXAMPLE_REVIEWER_ID, roles: ["reviewer"] };

function reads(dto: ReviewTaskDetailDto, overrides: Partial<WorkbenchReads> = {}): WorkbenchReads {
  return {
    detail: reviewTaskDetailFromDto(dto),
    ontology: ok(ontologyFixture()),
    documents: new Map([[EXAMPLE_DOCUMENT_ID, ok(documentFromDto(documentDto()))]]),
    stored: new Map(),
    ruleVersions: ok([ruleVersionFromDto(ruleVersionDto())]),
    relations: null,
    targets: null,
    ruleKeys: [],
    access: { allowed: true },
    lifecycle: { allowed: true },
    ...overrides,
  };
}

describe("workbenchView of a seed task", () => {
  it("states the task, its draft in words, its source and its history", () => {
    const view = workbenchView(reads(reviewTaskDetailDto()), ANALYST);
    expect(view).toMatchObject({
      taskId: EXAMPLE_TASK_ID,
      title: "Example rule title",
      candidateTask: false,
      candidate: null,
      facts: {
        kind: "Seed draft",
        status: "Open",
        regulator: "example_regulator",
        priority: 50,
        claimed: null,
        decision: null,
        version: {
          ruleVersionId: EXAMPLE_VERSION_ID,
          label: "example_rule v1",
          status: "draft",
          highImpact: false,
          closed: false,
          needsReview: true,
          href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
        },
      },
      ontologyError: null,
    });
    expect(view.rule.draft).toMatchObject({
      ruleLabel: "example_rule v1",
      level: "Each registration",
      period: "From 1 Apr 2000, open-ended",
      recurrence: "Monthly, due on day 20 of the month after the period",
      template: { title: "Example obligation", due: null, evidence: "Example evidence" },
      todo: ["Example question for the analyst?"],
    });
    expect(view.rule.draft?.specification).toMatchObject({ kind: "group", mode: "all_of" });
    expect(view.source.documents.map((document) => document.documentId)).toEqual([
      EXAMPLE_DOCUMENT_ID,
    ]);
    expect(view.source.documents[0]?.clauses?.[0]?.quotes).toBe(1);
    expect(view.history.tasks[0]).toMatchObject({ taskId: EXAMPLE_TASK_ID, current: true });
    expect(view.comparisons).toEqual({ proposal: null, previous: null, previousError: null });
    expect(view.editorOntology?.attributes[0]).toEqual({
      key: "example_kind",
      type: "enum",
      definition: "Example definition of example_kind.",
      options: [
        { value: "first", label: "Example first kind" },
        { value: "second", label: "Example second kind" },
      ],
    });
  });

  it("offers the claim on an open task, and says why the draft is not edited yet", () => {
    const view = workbenchView(reads(reviewTaskDetailDto()), ANALYST);
    expect(view.rule.claim).toEqual({ state: "open", canClaim: true });
    expect(view.rule.edit).toBeNull();
    expect(view.rule.editBlocked).toBe(
      "Claim the task to edit its draft: only the analyst who claimed it edits it.",
    );
    expect(view.rule.draftForm).toBeNull();
    expect(view.rule.decide).toEqual({
      candidateTask: false,
      drafted: true,
      canApprove: false,
      approveBlocked: "Approving is a reviewer's or an admin's: you can return or reject.",
      canReturn: true,
      returnBlocked: null,
      canReject: true,
      rejectBlocked: null,
      highImpact: false,
    });
    expect(view.rule.approvals).toEqual({
      count: 0,
      required: 1,
      approvers: [],
      waitingForAnother: false,
    });
    expect(view.rule.publishHref).toBeNull();
  });

  it("gives the claimant the edit form, starting from the stored draft", () => {
    const view = workbenchView(
      reads(
        reviewTaskDetailDto({
          task: reviewTaskDto({
            status: "claimed",
            claimed_by: EXAMPLE_ANALYST_ID,
            claimed_at: "2000-05-01T05:00:00Z",
          }),
        }),
      ),
      ANALYST,
    );
    expect(view.rule.claim).toEqual({ state: "mine", at: "1 May 2000, 10:30 am IST" });
    expect(view.rule.editBlocked).toBeNull();
    expect(view.rule.edit?.initial).toMatchObject({
      title: "Example rule title",
      effectiveFrom: "2000-04-01",
      effectiveTo: "",
      frequency: "monthly",
      dueDay: "20",
      dueMonthOffset: "0",
      templateTitle: "Example obligation",
      templateSteps: "Example first step\nExample second step",
      templateDueInDays: "",
      templateEvidence: "example_evidence",
      todo: "Example question for the analyst?",
    });
    expect(view.rule.edit?.clauseOptions[0]).toMatchObject({
      value: EXAMPLE_CLAUSE_IDS.first,
      label: "en.p1 (Example 1/2000): Example clause text that opens the document.",
    });
    expect(view.rule.edit?.revision).toMatch(/^draft:1:/);
  });

  it("names someone else's claim and keeps the edit theirs", () => {
    const view = workbenchView(
      reads(
        reviewTaskDetailDto({
          task: reviewTaskDto({
            status: "claimed",
            claimed_by: EXAMPLE_OTHER_ANALYST_ID,
            claimed_at: null,
          }),
        }),
      ),
      ANALYST,
    );
    expect(view.rule.claim).toEqual({
      state: "other",
      by: { userId: EXAMPLE_OTHER_ANALYST_ID, you: false },
      at: null,
    });
    expect(view.rule.editBlocked).toBe(
      "Another analyst claimed this task: only they edit its draft.",
    );
  });

  it("offers a reviewer the approval, and says the round waits for a second reviewer", () => {
    const view = workbenchView(
      reads(
        reviewTaskDetailDto({
          rule_version: ruleVersionDto({ status: "in_review", high_impact: true }),
          approved_by: [EXAMPLE_ANALYST_ID],
          required_approvals: 2,
        }),
      ),
      REVIEWER,
    );
    expect(view.rule.decide).toMatchObject({
      canApprove: true,
      approveBlocked: null,
      highImpact: true,
    });
    expect(view.rule.approvals).toEqual({
      count: 1,
      required: 2,
      approvers: [{ userId: EXAMPLE_ANALYST_ID, you: false }],
      waitingForAnother: true,
    });
    expect(view.rule.editBlocked).toBe(
      "The version is under review: approve it, or return it to draft to edit it.",
    );
  });

  it("shows a decided task read-only, with the approved version's page to publish from", () => {
    const view = workbenchView(
      reads(
        reviewTaskDetailDto({
          task: reviewTaskDto({
            status: "decided",
            decision: "approve",
            decided_by: EXAMPLE_REVIEWER_ID,
            decided_at: "2000-05-02T06:00:00Z",
            note: "Example why",
          }),
          rule_version: ruleVersionDto({ status: "approved", seed_status: "reviewed" }),
        }),
      ),
      REVIEWER,
    );
    expect(view.rule.claim).toEqual({ state: "decided" });
    expect(view.rule.decide).toBeNull();
    expect(view.rule.editBlocked).toBe("This task is decided: its draft no longer changes here.");
    expect(view.rule.publishHref).toBe(`/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`);
    expect(view.facts.decision).toEqual({
      label: "Approved",
      by: { userId: EXAMPLE_REVIEWER_ID, you: true },
      at: "2 May 2000, 11:30 am IST",
      note: "Example why",
    });
  });

  it("says a closed draft never moves on, and a version in another status is not edited", () => {
    const closed = workbenchView(
      reads(reviewTaskDetailDto({ rule_version: ruleVersionDto({ closed: true }) })),
      REVIEWER,
    );
    expect(closed.rule.editBlocked).toBe(
      "This draft is closed: its candidate was rejected, so it never moves on.",
    );
    expect(closed.rule.decide?.approveBlocked).toBe(
      "This draft is closed: its candidate was rejected, so it never moves on.",
    );
    const published = workbenchView(
      reads(reviewTaskDetailDto({ rule_version: ruleVersionDto({ status: "published" }) })),
      REVIEWER,
    );
    expect(published.rule.editBlocked).toBe("The version is Published: only a draft is edited.");
    expect(published.rule.decide?.approveBlocked).toBe(
      "The version is Published: only a draft is edited.",
    );
  });

  it("compares the draft with the rule's previous version, and says when it could not read them", () => {
    const previous = ruleVersionFromDto(
      ruleVersionDto({
        rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        version: 1,
        status: "published",
        title: "Example earlier title",
      }),
    );
    const current = ruleVersionDto({ version: 2 });
    const view = workbenchView(
      reads(reviewTaskDetailDto({ rule_version: current }), {
        ruleVersions: ok([previous, ruleVersionFromDto(current)]),
      }),
      ANALYST,
    );
    expect(view.comparisons.previous).toMatchObject({
      title: "example_rule v1 and this draft",
      beforeLabel: "Version 1",
      afterLabel: "This draft",
      changed: [
        {
          field: "title",
          lines: [
            { kind: "removed", text: "Example earlier title" },
            { kind: "added", text: "Example rule title" },
          ],
        },
      ],
    });
    const failed = workbenchView(
      reads(reviewTaskDetailDto(), {
        ruleVersions: err(webError("server", "example", "Example failure")),
      }),
      ANALYST,
    );
    expect(failed.comparisons.previousError).toMatchObject({ message: "Example failure" });
  });

  it("offers no step and says why when the access is refused, and words values as stored without the ontology", () => {
    const view = workbenchView(
      reads(
        reviewTaskDetailDto({
          task: reviewTaskDto({ status: "claimed", claimed_by: EXAMPLE_ANALYST_ID }),
        }),
        {
          access: { allowed: false, title: "The web.admin_rulebook_writes flag is off" },
          ontology: err(webError("unavailable", "example", "Example ontology away")),
        },
      ),
      ANALYST,
    );
    expect(view.rule.edit).toBeNull();
    expect(view.rule.editBlocked).toBe("The web.admin_rulebook_writes flag is off");
    expect(view.rule.decide).toBeNull();
    expect(view.editorOntology).toBeNull();
    expect(view.ontologyError).toMatchObject({ message: "Example ontology away" });
  });
});

describe("workbenchView of a candidate task", () => {
  it("shows the candidate and asks for the claim before drafting", () => {
    const view = workbenchView(reads(candidateTaskDetailDto(), { ruleVersions: null }), ANALYST);
    expect(view).toMatchObject({
      taskId: EXAMPLE_CANDIDATE_TASK_ID,
      title: "Example candidate title",
      candidateTask: true,
      facts: { kind: "Rule candidate", version: null },
    });
    expect(view.candidate).toMatchObject({
      suggestedKey: "example_suggested_rule",
      suggestedKnown: false,
    });
    expect(view.rule.draft).toBeNull();
    expect(view.rule.draftForm).toBeNull();
    expect(view.rule.draftBlocked).toBe("Claim the task to draft a version from the candidate.");
    expect(view.rule.decide).toMatchObject({
      candidateTask: true,
      drafted: false,
      canApprove: false,
      approveBlocked:
        "Approving needs a drafted version: draft one from the candidate first. Until then the task can only be rejected.",
      canReturn: false,
      canReject: true,
    });
    expect(view.rule.approvals).toBeNull();
    expect(view.source.documents[0]).toMatchObject({
      documentId: EXAMPLE_DOCUMENT_ID,
      role: "candidate",
    });
    expect(view.source.documents[0]?.clauses?.[0]?.quotes).toBe(1);
  });

  it("gives the claimant the draft form, from the proposal, with the relations and their versions", () => {
    const target = ruleVersionFromDto(
      ruleVersionDto({
        rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        rule_key: "example_target",
        status: "published",
      }),
    );
    const closed = ruleVersionFromDto(
      ruleVersionDto({ rule_key: "example_target", version: 2, closed: true }),
    );
    const view = workbenchView(
      reads(
        candidateTaskDetailDto({
          task: reviewTaskDto({
            task_id: EXAMPLE_CANDIDATE_TASK_ID,
            rule_version_id: null,
            kind: "candidate",
            status: "claimed",
            claimed_by: EXAMPLE_ANALYST_ID,
          }),
        }),
        {
          ruleVersions: null,
          relations: ok([
            relationCandidateFromDto(
              relationCandidateDto({
                candidate_id: EXAMPLE_RELATION_CANDIDATE_ID,
                relation: "supersedes",
                target_rule_key: "example_target",
              }),
            ),
          ]),
          targets: ok([target, closed]),
          ruleKeys: ["example_rule", "example_target"],
        },
      ),
      ANALYST,
    );
    expect(view.rule.draftBlocked).toBeNull();
    expect(view.rule.draftForm).toMatchObject({
      ruleKey: "example_suggested_rule",
      suggestedKnown: false,
      regulator: "example_regulator",
      ruleKeys: ["example_rule", "example_target"],
      relationsError: null,
      proposedCitations: [{ clauseRef: "en.p1", quote: "Example clause text that opens" }],
      initial: {
        title: "Example candidate title",
        effectiveFrom: "2000-04-01",
        frequency: "",
        templateDueInDays: "30",
        todo: "",
      },
    });
    expect(view.rule.draftForm?.relations).toEqual([
      {
        candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
        label: "Supersedes: EXAMPLE-1",
        evidenceQuote: "clause text that opens",
        needsTarget: true,
        targetOptions: [
          { value: EXAMPLE_OTHER_VERSION_ID, label: "example_target v1 (Published)" },
        ],
      },
    ]);
  });

  it("compares a drafted candidate's proposal with its draft", () => {
    const view = workbenchView(
      reads(
        candidateTaskDetailDto({
          task: reviewTaskDto({
            task_id: EXAMPLE_CANDIDATE_TASK_ID,
            kind: "candidate",
            candidate_id: ruleCandidateDto().candidate_id,
          }),
          rule_version: ruleVersionDto({ title: "Example candidate title" }),
          candidate: ruleCandidateDto({ status: "drafted", rule_version_id: EXAMPLE_VERSION_ID }),
        }),
      ),
      ANALYST,
    );
    expect(view.comparisons.proposal).toMatchObject({
      title: "The candidate's proposal and the draft",
      beforeLabel: "Proposed",
      afterLabel: "This draft",
    });
    const fields = view.comparisons.proposal?.changed.map((field) => field.field);
    expect(fields).toContain("summary");
    expect(fields).toContain("specification");
    expect(view.comparisons.proposal?.same).toContain("Title");
  });
});

describe("the helpers", () => {
  it("lists the candidate's document first, then each cited one once", () => {
    const detail = reviewTaskDetailFromDto(
      candidateTaskDetailDto({
        documents: [
          { ...reviewTaskDetailDto().documents[0], document_id: EXAMPLE_DOCUMENT_ID } as never,
        ],
      }),
    );
    expect(sourceDocumentIds(detail)).toEqual([EXAMPLE_DOCUMENT_ID]);
  });

  it("takes the latest earlier version that is not closed as the previous one", () => {
    const versions = [1, 2, 3].map((version) =>
      ruleVersionFromDto(ruleVersionDto({ version, closed: version === 2 })),
    );
    expect(previousVersion(versions, versions[2] as never)?.version).toBe(1);
    expect(previousVersion(versions, versions[0] as never)).toBeNull();
  });

  it("keeps only what the predicate editor needs of the ontology", () => {
    expect(Object.keys(editorOntology(ontologyFixture()))).toEqual([
      "attributes",
      "operatorsByType",
    ]);
  });
});

describe("the steps that move the version's lifecycle", () => {
  const OFF = {
    allowed: false as const,
    title: "The web.publish_actions flag is off",
  };
  const WAITS =
    "The web.publish_actions flag is off: approving, returning and rejecting a drafted version move its lifecycle, which waits for that flag here as it does on the version's page.";

  it("hold back approving, returning and rejecting a drafted version, saying why", () => {
    const view = workbenchView(reads(reviewTaskDetailDto(), { lifecycle: OFF }), REVIEWER);
    expect(view.rule.decide).toMatchObject({
      canApprove: false,
      approveBlocked: WAITS,
      canReturn: false,
      returnBlocked: WAITS,
      canReject: false,
      rejectBlocked: WAITS,
    });
    // The claim and the edit stay under web.admin_rulebook_writes alone.
    expect(view.rule.claim).toEqual({ state: "open", canClaim: true });
  });

  it("leave a rejection before drafting to web.admin_rulebook_writes, and an analyst the role's words", () => {
    const candidate = workbenchView(reads(candidateTaskDetailDto(), { lifecycle: OFF }), ANALYST);
    expect(candidate.rule.decide).toMatchObject({
      drafted: false,
      canApprove: false,
      canReturn: false,
      returnBlocked: null,
      canReject: true,
      rejectBlocked: null,
    });
    const analyst = workbenchView(reads(reviewTaskDetailDto(), { lifecycle: OFF }), ANALYST);
    expect(analyst.rule.decide?.approveBlocked).toBe(
      "Approving is a reviewer's or an admin's: you can return or reject.",
    );
  });
});

describe("checkRelations", () => {
  const OFFERED: RelationChoice[] = [
    {
      candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
      label: "Supersedes: EXAMPLE-1",
      evidenceQuote: "Example clause text",
      needsTarget: true,
      targetOptions: [{ value: EXAMPLE_OTHER_VERSION_ID, label: "example_rule v1 (Published)" }],
    },
    {
      candidateId: EXAMPLE_TASK_ID,
      label: "Refers to: EXAMPLE-2",
      evidenceQuote: "Example clause text",
      needsTarget: false,
      targetOptions: [{ value: EXAMPLE_VERSION_ID, label: "example_rule v2 (Draft)" }],
    },
  ];

  it("passes relations the form offered, with a version where the kind needs one", () => {
    expect(
      checkRelations(
        [
          {
            candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
            targetRuleVersionId: EXAMPLE_OTHER_VERSION_ID,
          },
          { candidateId: EXAMPLE_TASK_ID, targetRuleVersionId: null },
        ],
        OFFERED,
      ),
    ).toEqual({});
  });

  it("refuses a candidate not offered, a missing target and a version outside the row's choices", () => {
    const stranger = "00000000-0000-4000-8000-0000000000f9";
    expect(
      checkRelations(
        [
          { candidateId: EXAMPLE_RELATION_CANDIDATE_ID, targetRuleVersionId: null },
          { candidateId: EXAMPLE_TASK_ID, targetRuleVersionId: stranger },
          { candidateId: EXAMPLE_CANDIDATE_TASK_ID, targetRuleVersionId: null },
        ],
        OFFERED,
      ),
    ).toEqual({
      [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: [
        "Choose the version this relation points at.",
      ],
      [relationField(EXAMPLE_TASK_ID, "target")]: [
        "Choose one of the versions offered for this relation.",
      ],
      [relationField(EXAMPLE_CANDIDATE_TASK_ID, "take")]: [
        "This relation candidate is not open on the candidate's document any more: untick it.",
      ],
    });
  });
});
