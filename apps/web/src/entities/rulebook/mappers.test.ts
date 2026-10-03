import { describe, expect, it } from "vitest";
import { documentDto } from "@/test/rulebook-fixture";
import {
  approvalToDto,
  approvedFromDto,
  clauseFromDto,
  documentFromDto,
  entityDecidedFromDto,
  entityDecisionToDto,
  rejectionToDto,
  relationCandidateFromDto,
} from "./mappers";
import type { RelationCandidateDto } from "./types";

describe("documentFromDto", () => {
  it("maps every field and puts the clauses in reading order", () => {
    const document = documentFromDto(documentDto());
    expect(document).toMatchObject({
      documentId: "00000000-0000-0000-0000-00000000d0c1",
      sourceId: "00000000-0000-4000-8000-000000000000",
      regulator: "Example regulator",
      docType: "circular",
      externalRef: "Example 1/2000",
      title: "Example document title",
      language: "en",
      mediaType: "application/pdf",
      parserVersion: "example@0",
      publishedAt: "2000-01-15",
    });
    expect(document.clauses.map((clause) => clause.clauseRef)).toEqual(["en.p1", "en.p2", "en.p3"]);
  });

  it("keeps a missing page and a missing publication date as null", () => {
    expect(
      clauseFromDto({
        clause_id: "c",
        clause_ref: "en.p9",
        ordinal: 9,
        page: null,
        text: "Example clause text",
      }).page,
    ).toBeNull();
    expect(documentFromDto(documentDto({ published_at: null })).publishedAt).toBeNull();
  });
});

describe("the decision mappers", () => {
  const candidate: RelationCandidateDto = {
    candidate_id: "00000000-0000-4000-8000-0000000000c1",
    document_id: "00000000-0000-0000-0000-00000000d0c1",
    relation: "extends_deadline",
    target_type: "form",
    target_name: "Example form",
    target_entity_id: "00000000-0000-4000-8000-0000000000e1",
    target_rule_key: "example.rule",
    evidence_clause_id: "00000000-0000-5000-8000-0000000000c1",
    evidence_quote: "Example clause text",
    quote_score: 1,
    period_label: "Example period",
    new_due_on: "2000-02-20",
    prompt_version: "example@0",
    model: "example-model",
    confidence: 0.5,
    issues: [{ code: "rule_key_unknown", detail: "Example detail" }],
    needs_review: false,
    status: "open",
    reject_reason: null,
    decided_by: "",
  };

  it("keeps a candidate's optional values when the rulebook sends them", () => {
    expect(relationCandidateFromDto(candidate)).toMatchObject({
      relation: "extends_deadline",
      targetEntityId: "00000000-0000-4000-8000-0000000000e1",
      targetRuleKey: "example.rule",
      periodLabel: "Example period",
      newDueOn: "2000-02-20",
      issues: [{ code: "rule_key_unknown", detail: "Example detail" }],
      needsReview: false,
      rejectReason: null,
    });
  });

  it("writes decided_by from the caller's argument into every decision body", () => {
    expect(
      entityDecisionToDto(
        { entityType: "form", proposedName: "Example form", decision: "create_entity", note: "" },
        "example-user",
      ),
    ).toEqual({
      entity_type: "form",
      proposed_name: "Example form",
      decision: "create_entity",
      decided_by: "example-user",
      note: "",
    });
    expect(rejectionToDto({ reason: "out_of_scope", note: "" }, "example-user")).toEqual({
      reason: "out_of_scope",
      decided_by: "example-user",
      note: "",
    });
    expect(
      approvalToDto({ fromRuleVersionId: "example-version", note: "" }, "example-user"),
    ).toEqual({ from_rule_version_id: "example-version", decided_by: "example-user", note: "" });
  });

  it("maps a decision's outcome", () => {
    expect(
      entityDecidedFromDto({
        status: "decided",
        resolution: null,
        entity_id: null,
        items_closed: 0,
        relation_targets_updated: 0,
      }),
    ).toEqual({
      status: "decided",
      resolution: null,
      entityId: null,
      itemsClosed: 0,
      relationTargetsUpdated: 0,
    });
    expect(approvedFromDto({ candidate_id: "c", rule_relation_id: "r" })).toEqual({
      candidateId: "c",
      ruleRelationId: "r",
    });
  });
});
