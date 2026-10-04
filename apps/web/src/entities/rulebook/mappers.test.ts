import { describe, expect, it } from "vitest";
import { documentDto } from "@/test/rulebook-fixture";
import {
  approvalToDto,
  approvedFromDto,
  clauseDetailFromDto,
  clauseFromDto,
  documentFromDto,
  entityDecidedFromDto,
  entityDecisionToDto,
  entityFromDto,
  mentionedClauseFromDto,
  rejectionToDto,
  relationCandidateFromDto,
  relationFromDto,
  resolutionFromDto,
  searchHitFromDto,
  searchToDto,
} from "./mappers";
import type { ClauseDetailDto, EntityDto, RelationCandidateDto, RelationDto } from "./types";

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

const ENTITY: EntityDto = {
  entity_id: "00000000-0000-4000-8000-0000000000e1",
  entity_type: "form",
  canonical_name: "example form",
  aliases: ["example form 1"],
};

const CLAUSE_DETAIL: ClauseDetailDto = {
  clause_id: "00000000-0000-5000-8000-0000000000c1",
  document_id: "00000000-0000-0000-0000-00000000d0c1",
  clause_ref: "en.p1",
  ordinal: 1,
  page: null,
  text: "Example clause text",
  regulator: "Example regulator",
  doc_type: "circular",
  external_ref: "Example 1/2000",
  title: "Example document title",
  url: "https://example.com/example-document.pdf",
  language: "en",
  published_at: null,
};

describe("the knowledge graph mappers", () => {
  it("map an entity and each resolution with its entity or candidates", () => {
    expect(entityFromDto(ENTITY)).toEqual({
      entityId: "00000000-0000-4000-8000-0000000000e1",
      entityType: "form",
      canonicalName: "example form",
      aliases: ["example form 1"],
    });
    expect(
      resolutionFromDto({
        status: "resolved",
        entity_type: "form",
        name: "Example Form",
        normalised: "example form",
        entity: ENTITY,
        candidates: [],
      }),
    ).toMatchObject({ status: "resolved", entity: { canonicalName: "example form" } });
    expect(
      resolutionFromDto({
        status: "ambiguous",
        entity_type: "form",
        name: "Example",
        normalised: "example",
        entity: null,
        candidates: [ENTITY, { ...ENTITY, entity_id: "00000000-0000-4000-8000-0000000000e2" }],
      }),
    ).toMatchObject({ status: "ambiguous", entity: null, candidates: [{}, {}] });
  });

  it("map a clause with its document's facts, and a mentioned clause with its spans", () => {
    expect(clauseDetailFromDto(CLAUSE_DETAIL)).toMatchObject({
      clauseRef: "en.p1",
      page: null,
      docType: "circular",
      externalRef: "Example 1/2000",
      publishedAt: null,
    });
    expect(
      mentionedClauseFromDto({
        ...CLAUSE_DETAIL,
        published_at: "2000-01-15",
        mentions: [{ text: "Example", span_start: 0, span_end: 7 }],
        out_of_force: true,
      }),
    ).toMatchObject({
      publishedAt: "2000-01-15",
      mentions: [{ text: "Example", start: 0, end: 7 }],
      outOfForce: true,
    });
  });

  it("maps a relation to a version and to an entity", () => {
    const relation: RelationDto = {
      relation_id: "00000000-0000-4000-8000-0000000000b1",
      from_rule_version_id: "00000000-0000-4000-8000-0000000000f1",
      relation: "extends_deadline",
      to_kind: "rule_version",
      to_ref: "00000000-0000-4000-8000-0000000000f2",
      to_rule_version_id: "00000000-0000-4000-8000-0000000000f2",
      to_entity_id: null,
      evidence_clause_id: "00000000-0000-5000-8000-0000000000c1",
      evidence_clause_ref: "en.p1",
      evidence_document_id: "00000000-0000-0000-0000-00000000d0c1",
      candidate_id: null,
      period_label: "2000-03",
      new_due_on: "2000-04-21",
    };
    expect(relationFromDto(relation)).toEqual({
      relationId: "00000000-0000-4000-8000-0000000000b1",
      fromRuleVersionId: "00000000-0000-4000-8000-0000000000f1",
      relation: "extends_deadline",
      toKind: "rule_version",
      toRef: "00000000-0000-4000-8000-0000000000f2",
      toRuleVersionId: "00000000-0000-4000-8000-0000000000f2",
      toEntityId: null,
      evidenceClauseId: "00000000-0000-5000-8000-0000000000c1",
      evidenceClauseRef: "en.p1",
      evidenceDocumentId: "00000000-0000-0000-0000-00000000d0c1",
      candidateId: null,
      periodLabel: "2000-03",
      newDueOn: "2000-04-21",
    });
    expect(
      relationFromDto({
        ...relation,
        relation: "refers_to",
        to_kind: "form",
        to_ref: "example form",
        to_rule_version_id: null,
        to_entity_id: "00000000-0000-4000-8000-0000000000e1",
        period_label: null,
        new_due_on: null,
      }),
    ).toMatchObject({ toKind: "form", toEntityId: "00000000-0000-4000-8000-0000000000e1" });
  });
});

describe("the search mappers", () => {
  it("send the text with the filters given, and no vector", () => {
    expect(searchToDto({ text: "Example words", docTypes: [], k: 8 })).toEqual({
      text: "Example words",
      k: 8,
      doc_types: [],
    });
    expect(
      searchToDto({
        text: "Example words",
        docTypes: ["circular"],
        k: 20,
        regulator: "Example regulator",
        asOf: "2000-06-30",
      }),
    ).toEqual({
      text: "Example words",
      k: 20,
      doc_types: ["circular"],
      regulator: "Example regulator",
      as_of: "2000-06-30",
    });
  });

  it("map a hit with the rank of each leg", () => {
    expect(
      searchHitFromDto({
        ...CLAUSE_DETAIL,
        score: 0.0328,
        lexical_rank: 1,
        vector_rank: null,
        cited_by: ["00000000-0000-4000-8000-0000000000f1"],
        out_of_force: false,
      }),
    ).toMatchObject({
      clauseRef: "en.p1",
      score: 0.0328,
      lexicalRank: 1,
      vectorRank: null,
      citedBy: ["00000000-0000-4000-8000-0000000000f1"],
      outOfForce: false,
    });
  });
});
