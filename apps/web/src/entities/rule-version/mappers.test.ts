import { describe, expect, it } from "vitest";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  citationDto,
  lifecycleDto,
  publicationDto,
  ruleDto,
  ruleVersionDetailDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  actorToDto,
  citationFromDto,
  citationReportFromDto,
  citationsToDto,
  lifecycleFromDto,
  obligationTemplateFromMapping,
  publicationFromDto,
  recurrenceFromMapping,
  ruleFromDto,
  ruleVersionFromDto,
  sourceFromMapping,
  specificationFromMapping,
  submitToDto,
  versionApprovalToDto,
} from "./mappers";

describe("ruleVersionFromDto", () => {
  it("maps the version and reads its open mappings", () => {
    const version = ruleVersionFromDto(ruleVersionDto());
    expect(version).toMatchObject({
      ruleVersionId: EXAMPLE_VERSION_ID,
      ruleKey: "example_rule",
      version: 1,
      status: "draft",
      title: "Example rule title",
      effectiveFrom: "2000-04-01",
      effectiveTo: null,
      seedStatus: "needs_review",
      needsReview: true,
      todo: ["Example question for the analyst?"],
      publishedAt: null,
      highImpact: false,
      obligationTemplate: {
        title: "Example obligation",
        steps: ["Example first step", "Example second step"],
        dueInDays: null,
        evidenceType: "example_evidence",
      },
      recurrence: { frequency: "monthly", dueDay: 20, dueMonthOffset: 0 },
      source: {
        instrument: "Example instrument, 2000",
        reference: "Example reference 1(1)",
        note: "Example note on the source.",
        url: "",
      },
    });
    expect(version.specification).toEqual({
      kind: "all_of",
      items: [
        {
          kind: "predicate",
          attribute: "example_kind",
          operator: "eq",
          values: ["first"],
          multi: false,
          freeText: "",
        },
        {
          kind: "predicate",
          attribute: "example_band",
          operator: "gt",
          values: ["small"],
          multi: false,
          freeText: "",
        },
        {
          kind: "not",
          item: {
            kind: "predicate",
            attribute: "state_codes",
            operator: "contains_any",
            values: ["01", "02"],
            multi: true,
            freeText: "",
          },
        },
        {
          kind: "predicate",
          attribute: "example_question",
          operator: null,
          values: [],
          multi: false,
          freeText: "Example condition an analyst judges.",
        },
      ],
    });
    expect(version.stored.recurrence).toEqual({
      frequency: "monthly",
      due_day: 20,
      due_month_offset: 0,
    });
  });

  it("maps a reviewed, published, high-impact version from the detail route", () => {
    const version = ruleVersionFromDto(
      ruleVersionDetailDto({
        status: "published",
        seed_status: "reviewed",
        published_at: "2000-05-02T06:00:00Z",
        effective_to: "2001-04-01",
        high_impact: true,
        recurrence: null,
        approved_by: [EXAMPLE_ANALYST_ID],
      }),
    );
    expect(version).toMatchObject({
      status: "published",
      needsReview: false,
      publishedAt: "2000-05-02T06:00:00Z",
      approvedBy: [EXAMPLE_ANALYST_ID],
      effectiveTo: "2001-04-01",
      highImpact: true,
      recurrence: null,
    });
    expect(version.stored.recurrence).toBeNull();
    expect(ruleVersionFromDto(ruleVersionDto()).approvedBy).toEqual([]);
  });
});

describe("specificationFromMapping", () => {
  it("reads an empty mapping as no condition yet", () => {
    expect(specificationFromMapping({})).toBeNull();
  });

  it("reads any_of, a boolean value and a free text hint beside an operator", () => {
    expect(
      specificationFromMapping({
        any_of: [
          { attribute: "example_flag", operator: "eq", value: true },
          { attribute: "example_count", operator: "in", value: [1, 2], free_text: "Example hint" },
        ],
      }),
    ).toEqual({
      kind: "any_of",
      items: [
        {
          kind: "predicate",
          attribute: "example_flag",
          operator: "eq",
          values: [true],
          multi: false,
          freeText: "",
        },
        {
          kind: "predicate",
          attribute: "example_count",
          operator: "in",
          values: [1, 2],
          multi: true,
          freeText: "Example hint",
        },
      ],
    });
  });

  it("keeps a shape the kernel does not write as unreadable, with its mapping", () => {
    const shapes: unknown[] = [
      "example",
      [],
      { example: 1 },
      { attribute: "example_kind" },
      { attribute: "example_kind", operator: "eq" },
      { attribute: "example_kind", value: "example_a" },
      { attribute: "example_kind", operator: "eq", value: { nested: true } },
      { attribute: 1, operator: "eq", value: "example_a" },
      { attribute: "example_kind", operator: "eq", value: "example_a", extra: true },
    ];
    for (const raw of shapes) {
      expect(specificationFromMapping(raw), JSON.stringify(raw)).toEqual({
        kind: "unreadable",
        raw,
      });
    }
    expect(specificationFromMapping({ not: "example" })).toEqual({
      kind: "not",
      item: { kind: "unreadable", raw: "example" },
    });
  });
});

describe("the open mappings", () => {
  it("leave an obligation template without a title and a recurrence without a frequency out", () => {
    expect(obligationTemplateFromMapping({ steps: ["Example step"] })).toBeNull();
    expect(obligationTemplateFromMapping("example")).toBeNull();
    expect(recurrenceFromMapping({ due_day: 1 })).toBeNull();
    expect(recurrenceFromMapping(null)).toBeNull();
  });

  it("keep only the text steps and the whole numbers they know", () => {
    expect(
      obligationTemplateFromMapping({
        title: "Example",
        steps: ["Example step", 3],
        due_in_days: 30,
      }),
    ).toEqual({ title: "Example", steps: ["Example step"], dueInDays: 30, evidenceType: null });
    expect(
      recurrenceFromMapping({ frequency: "annual", due_day: "x", due_month_offset: 2 }),
    ).toEqual({ frequency: "annual", dueDay: null, dueMonthOffset: 2 });
  });

  it("read a source with missing parts as empty text", () => {
    expect(sourceFromMapping({ instrument: "Example instrument" })).toEqual({
      instrument: "Example instrument",
      reference: "",
      note: "",
      url: "",
    });
    expect(sourceFromMapping(null)).toEqual({ instrument: "", reference: "", note: "", url: "" });
  });
});

describe("the citation and rule mappers", () => {
  it("maps a rule and a citation", () => {
    expect(ruleFromDto(ruleDto())).toEqual({
      ruleKey: "example_rule",
      ruleId: "00000000-0000-4000-8000-0000000000a1",
      regulator: "example_regulator",
      title: "Example rule title",
    });
    expect(citationFromDto(citationDto({ match_score: null, verified_at: null }))).toMatchObject({
      clauseRef: "en.p1",
      quote: "Example clause text that opens",
      verified: true,
      matchScore: null,
      verifiedAt: null,
    });
  });

  it("maps what a save of citations stored", () => {
    expect(
      citationReportFromDto({ added: 1, unchanged: 2, citations: [citationDto()] }),
    ).toMatchObject({
      added: 1,
      unchanged: 2,
      citations: [{ matchScore: 0.97, verified: true }],
    });
  });

  it("sends the clause id and the quote of each citation", () => {
    expect(
      citationsToDto([
        { clauseId: "00000000-0000-5000-8000-0000000000c1", quote: "Example quote" },
      ]),
    ).toEqual({
      citations: [{ clause_id: "00000000-0000-5000-8000-0000000000c1", quote: "Example quote" }],
    });
  });
});

describe("the lifecycle mappers", () => {
  it("maps a step's answer with the round's approvers", () => {
    expect(lifecycleFromDto(lifecycleDto())).toEqual({
      ruleVersionId: EXAMPLE_VERSION_ID,
      ruleId: "00000000-0000-4000-8000-0000000000a1",
      version: 1,
      status: "in_review",
      seedStatus: "needs_review",
      highImpact: true,
      effectiveFrom: "2000-04-01",
      effectiveTo: null,
      submittedAt: "2000-05-01T06:00:00Z",
      publishedAt: null,
      approvedBy: [EXAMPLE_ANALYST_ID],
      requiredApprovals: 2,
      events: [],
    });
  });

  it("maps a publication with what it replaced and the events it wrote", () => {
    const publication = publicationFromDto(publicationDto());
    expect(publication).toMatchObject({
      status: "published",
      correlationId: "00000000-0000-4000-8000-0000000000e2",
      replacements: [
        {
          ruleVersionId: EXAMPLE_OTHER_VERSION_ID,
          relation: "supersedes",
          effectiveTo: "2000-04-01",
          status: "published",
          movesTo: "superseded",
          pending: true,
        },
      ],
      deadlineChanges: [],
      attributeKeys: ["example_band", "example_kind"],
      events: [{ eventId: "00000000-0000-4000-8000-0000000000e1", topic: "rule.published" }],
    });
    expect(
      publicationFromDto(
        publicationDto({
          deadline_changes: [
            {
              rule_version_id: EXAMPLE_OTHER_VERSION_ID,
              period_label: null,
              new_due_on: "2000-06-20",
              evidence_clause_id: "00000000-0000-5000-8000-0000000000c1",
            },
          ],
        }),
      ).deadlineChanges,
    ).toEqual([
      {
        ruleVersionId: EXAMPLE_OTHER_VERSION_ID,
        periodLabel: null,
        newDueOn: "2000-06-20",
        evidenceClauseId: "00000000-0000-5000-8000-0000000000c1",
      },
    ]);
  });
});

describe("the step bodies", () => {
  it("name the session's user as the actor", () => {
    expect(submitToDto({ highImpact: true, note: "Example note" }, EXAMPLE_ANALYST_ID)).toEqual({
      actor_id: EXAMPLE_ANALYST_ID,
      high_impact: true,
      note: "Example note",
    });
    expect(actorToDto("Example reason", EXAMPLE_ANALYST_ID)).toEqual({
      actor_id: EXAMPLE_ANALYST_ID,
      note: "Example reason",
    });
  });

  it("never mark an approval synthetic", () => {
    const body = versionApprovalToDto("", EXAMPLE_ANALYST_ID);
    expect(body).toEqual({ actor_id: EXAMPLE_ANALYST_ID, note: "" });
    expect(Object.keys(body)).not.toContain("synthetic");
  });
});
