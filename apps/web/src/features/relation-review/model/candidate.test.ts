import { describe, expect, it } from "vitest";
import { clauseDetailFromDto, relationCandidateFromDto } from "@/entities/rulebook/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  EXAMPLE_ENTITY_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import {
  approvedResult,
  candidateFacts,
  evidenceOf,
  lookupOrder,
  markQuote,
  needsTargetVersion,
  predecessorOf,
  rejectReasonText,
  rejectedResult,
  versionOptions,
} from "./candidate";

const CLAUSE = clauseDetailFromDto({
  clause_id: EXAMPLE_CLAUSE_IDS.first,
  document_id: EXAMPLE_DOCUMENT_ID,
  clause_ref: "en.p1",
  ordinal: 1,
  page: 1,
  text: "Example clause text that opens the document.",
  regulator: "Example regulator",
  doc_type: "circular",
  external_ref: "Example 1/2000",
  title: "Example document title",
  url: "https://example.com/example.pdf",
  language: "en",
  published_at: null,
});

function version(overrides: Parameters<typeof ruleVersionDto>[0]) {
  return ruleVersionFromDto(ruleVersionDto(overrides));
}

describe("predecessorOf", () => {
  it("gives the UUID just before one, borrowing across its groups", () => {
    expect(predecessorOf("00000000-0000-4000-8000-0000000000ca")).toBe(
      "00000000-0000-4000-8000-0000000000c9",
    );
    expect(predecessorOf("00000001-0000-0000-0000-000000000000")).toBe(
      "00000000-ffff-ffff-ffff-ffffffffffff",
    );
    expect(predecessorOf("ABCDEF00-0000-4000-8000-000000000001")).toBe(
      "abcdef00-0000-4000-8000-000000000000",
    );
  });

  it("has none for the nil UUID or something that is not one", () => {
    expect(predecessorOf("00000000-0000-0000-0000-000000000000")).toBeNull();
    expect(predecessorOf("not-an-id")).toBeNull();
  });
});

describe("lookupOrder", () => {
  it("looks in the address's status first, then the others", () => {
    expect(lookupOrder("rejected")).toEqual(["rejected", "open", "approved"]);
    expect(lookupOrder(undefined)).toEqual(["open", "approved", "rejected"]);
    expect(lookupOrder("example")).toEqual(["open", "approved", "rejected"]);
  });
});

describe("needsTargetVersion", () => {
  it("asks for a version for the version-only relations and a candidate naming a rule", () => {
    expect(needsTargetVersion({ relation: "supersedes", targetRuleKey: null })).toBe(true);
    expect(needsTargetVersion({ relation: "refers_to", targetRuleKey: "example_rule" })).toBe(true);
    expect(needsTargetVersion({ relation: "refers_to", targetRuleKey: null })).toBe(false);
  });
});

describe("the evidence", () => {
  it("marks the quote where the clause holds it word for word", () => {
    expect(markQuote("Example clause text.", "clause")).toEqual({
      before: "Example ",
      mark: "clause",
      after: " text.",
    });
    expect(markQuote("Example clause text.", "absent")).toBeNull();
    expect(markQuote("Example clause text.", "")).toBeNull();
  });

  it("reads the clause, its reference and its document, or keeps the quote alone", () => {
    const candidate = relationCandidateFromDto(relationCandidateDto());
    const evidence = evidenceOf(candidate, CLAUSE);
    expect(evidence).toMatchObject({
      quote: "clause text that opens",
      mark: { mark: "clause text that opens" },
      clauseRef: "en.p1",
      documentTitle: "Example document title",
      href: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    });
    expect(evidenceOf(candidate, null)).toMatchObject({ mark: null, clauseRef: null });
  });
});

describe("candidateFacts", () => {
  it("points an unaligned target at its entity review group", () => {
    const facts = candidateFacts(relationCandidateFromDto(relationCandidateDto()));
    expect(facts).toMatchObject({
      candidateId: EXAMPLE_CANDIDATE_ID,
      relationLabel: "Extends deadline",
      targetEntityHref: null,
      targetGroupHref: "/admin/rulebook/entities/group?type=form&name=EXAMPLE-1",
      open: true,
      issues: [{ code: "target_unaligned", label: "Target unaligned", detail: "Example detail" }],
      rejectReasonLabel: null,
    });
  });

  it("links an aligned target's entity and words a rejection", () => {
    const facts = candidateFacts(
      relationCandidateFromDto(
        relationCandidateDto({
          target_entity_id: EXAMPLE_ENTITY_ID,
          status: "rejected",
          reject_reason: "not_in_text",
          decided_by: "example-user",
        }),
      ),
    );
    expect(facts).toMatchObject({
      targetEntityHref: `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
      targetGroupHref: null,
      open: false,
      statusLabel: "Rejected",
      rejectReasonLabel: "Not in the text",
      decidedBy: "example-user",
    });
    expect(rejectReasonText("example_reason")).toBe("Example reason");
    expect(rejectReasonText("")).toBeNull();
  });
});

describe("versionOptions", () => {
  const versions = [
    version({ rule_key: "example_b", version: 2, status: "draft", rule_version_id: "v-b2" }),
    version({ rule_key: "example_a", version: 1, status: "published", rule_version_id: "v-a1" }),
    version({ rule_key: "example_a", version: 2, status: "draft", rule_version_id: "v-a2" }),
    version({
      rule_key: "example_a",
      version: 3,
      status: "draft",
      rule_version_id: "v-a3",
      closed: true,
    }),
  ];

  it("starts from the open drafts and points at the named rule's versions, never a closed one", () => {
    const options = versionOptions(versions, "example_a");
    expect(options.from.map((option) => option.value)).toEqual(["v-a2", "v-b2"]);
    expect(options.target.map((option) => option.value)).toEqual(["v-a1", "v-a2"]);
    expect(options.from[0]?.label).toBe("example_a v2 (Draft): Example rule title");
  });

  it("points at any rule's versions when the candidate names none", () => {
    expect(versionOptions(versions, null).target.map((option) => option.value)).toEqual([
      "v-a1",
      "v-a2",
      "v-b2",
    ]);
  });
});

describe("the results", () => {
  it("say what an approval wrote and where to see it, and why a candidate was rejected", () => {
    expect(approvedResult("relation-1", "v-a2")).toEqual({
      message: "Approved: rule relation relation-1 recorded.",
      ruleRelationId: "relation-1",
      graphHref: "/admin/rulebook/relations/graph?rule_version_id=v-a2",
    });
    expect(rejectedResult("A duplicate")).toEqual({
      message: "Rejected: A duplicate.",
      ruleRelationId: null,
      graphHref: null,
    });
  });
});
