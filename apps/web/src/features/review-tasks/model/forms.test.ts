import { describe, expect, it } from "vitest";
import { EXAMPLE_CLAUSE_IDS } from "@/test/rulebook-fixture";
import { EXAMPLE_OTHER_VERSION_ID } from "@/test/rule-version-fixture";
import { EXAMPLE_RELATION_CANDIDATE_ID, EXAMPLE_TASK_ID } from "@/test/review-task-fixture";
import { BASE_PREFIX, EDITS_PREFIX, relationField } from "../ui/form-shared";
import {
  canonical,
  parseCitations,
  parseClaim,
  parseContentChanges,
  parseDecision,
  parseDraft,
  parseEdit,
  parseRelations,
} from "./forms";

const SPEC = { all_of: [{ attribute: "example_kind", operator: "eq", value: "first" }] };

/** The content as rendered: every field with the same value now and as its base. */
const RENDERED: Record<string, string> = {
  title: "Example rule title",
  summary: "Example summary.",
  effective_from: "2000-04-01",
  effective_to: "",
  "recurrence.frequency": "monthly",
  "recurrence.due_day": "20",
  "recurrence.due_month_offset": "0",
  "obligation_template.title": "Example obligation",
  "obligation_template.steps": "Example first step\nExample second step",
  "obligation_template.due_in_days": "",
  "obligation_template.evidence_type": "example_evidence",
  todo: "Example question?",
  specification: JSON.stringify(SPEC),
};

function form(
  changes: Record<string, string> = {},
  extra: Record<string, string> = {},
  prefix = "",
): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(RENDERED)) {
    data.set(`${BASE_PREFIX}${prefix}${name}`, value);
    data.set(`${prefix}${name}`, changes[name] ?? value);
  }
  for (const [name, value] of Object.entries(extra)) data.set(name, value);
  return data;
}

describe("parseContentChanges", () => {
  it("sends nothing for a form left as it was rendered", () => {
    expect(parseContentChanges(form())).toEqual({ fields: {}, changed: 0, errors: {} });
  });

  it("sends each changed field in the kernel's forms, and only those", () => {
    const parsed = parseContentChanges(
      form({
        title: "  Example new title ",
        effective_to: "2001-04-01",
        "recurrence.frequency": "",
        "obligation_template.due_in_days": "30",
        todo: "\n Example first?\n\nExample second? \n",
        specification: JSON.stringify({ any_of: [] }),
      }),
    );
    expect(parsed.errors).toEqual({});
    expect(parsed.changed).toBe(6);
    expect(parsed.fields).toEqual({
      title: "Example new title",
      effectiveTo: "2001-04-01",
      recurrence: null,
      obligationTemplate: {
        title: "Example obligation",
        steps: ["Example first step", "Example second step"],
        due_in_days: 30,
        evidence_type: "example_evidence",
      },
      todo: ["Example first?", "Example second?"],
      specification: { any_of: [] },
    });
  });

  it("reads a recurrence and a condition as changed only when their content changed", () => {
    const reordered = { all_of: [{ value: "first", operator: "eq", attribute: "example_kind" }] };
    expect(
      parseContentChanges(
        form({ "recurrence.due_month_offset": "", specification: JSON.stringify(reordered) }),
      ).changed,
    ).toBe(0);
    expect(canonical({ b: 1, a: [{ d: 1, c: 2 }] })).toBe('{"a":[{"c":2,"d":1}],"b":1}');
  });

  it("checks the shape of a changed field only, under its own name", () => {
    const parsed = parseContentChanges(
      form({
        title: "",
        summary: "x".repeat(4001),
        effective_from: "01/04/2000",
        "recurrence.due_day": "32",
        "recurrence.due_month_offset": "25",
        "obligation_template.title": "",
        "obligation_template.due_in_days": "soon",
        todo: Array.from({ length: 21 }, (_, n) => `Example ${n}?`).join("\n"),
        specification: "{",
      }),
    );
    expect(parsed.fields).toEqual({});
    expect(parsed.errors).toEqual({
      title: ["Enter a title."],
      summary: ["At most 4000 characters."],
      effective_from: ["Enter a date as YYYY-MM-DD."],
      "recurrence.due_day": ["Enter a day of the month from 1 to 31."],
      "recurrence.due_month_offset": ["Enter a whole number of months from 0 to 24."],
      "obligation_template.title": ["Enter what the business has to do."],
      "obligation_template.due_in_days": ["Enter a whole number of days, or leave it empty."],
      todo: ["At most 20 questions."],
      specification: ["This is not valid JSON."],
    });
    expect(
      parseContentChanges(
        form({
          "recurrence.frequency": "weekly",
          todo: "x".repeat(501),
          specification: JSON.stringify({ all_of: {} }),
        }),
      ).errors,
    ).toEqual({
      "recurrence.frequency": ["Choose how often the duty recurs."],
      todo: ["A question has at most 500 characters."],
      specification: ["specification.all_of must be a list."],
    });
  });
});

describe("parseCitations", () => {
  it("reads the rows, skips blank ones and names the missing half of a row", () => {
    const data = new FormData();
    data.set("citations.0.clause_id", EXAMPLE_CLAUSE_IDS.first.toUpperCase());
    data.set("citations.0.quote", " Example clause text ");
    data.set("citations.1.clause_id", "");
    data.set("citations.1.quote", "");
    data.set("citations.2.clause_id", "not-an-id");
    data.set("citations.2.quote", "");
    data.set("citations.3.clause_id", EXAMPLE_CLAUSE_IDS.second);
    data.set("citations.3.quote", "x".repeat(401));
    expect(parseCitations(data)).toEqual({
      citations: [{ clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example clause text" }],
      errors: {
        "citations.2.clause_id": ["Choose the clause the quote is from."],
        "citations.2.quote": ["Type or paste the words of the clause."],
        "citations.3.quote": ["At most 400 characters."],
      },
    });
  });
});

describe("parseEdit", () => {
  it("takes the changed fields, the citations and the note", () => {
    const parsed = parseEdit(
      form(
        { summary: "Example new summary." },
        {
          "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
          "citations.0.quote": "Example clause text",
          note: " Example why ",
        },
      ),
    );
    expect(parsed).toEqual({
      ok: true,
      value: {
        fields: { summary: "Example new summary." },
        citations: [{ clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example clause text" }],
        note: "Example why",
      },
    });
  });

  it("says nothing changed before any request, and refuses a note that is too long", () => {
    expect(parseEdit(form())).toEqual({
      ok: false,
      errors: {},
      formErrors: ["Nothing changed: change a field or add a citation, then save."],
    });
    expect(parseEdit(form({ title: "Example" }, { note: "x".repeat(2001) }))).toEqual({
      ok: false,
      errors: { note: ["At most 2000 characters."] },
      formErrors: [],
    });
  });
});

describe("parseDraft", () => {
  it("drafts into a rule with the candidate's quotes and the relations taken on", () => {
    const parsed = parseDraft(
      form(
        { title: "Example edited title" },
        {
          rule_key: "example_rule",
          citations_mode: "candidate",
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on",
          [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: EXAMPLE_OTHER_VERSION_ID,
          // A row left unticked sends its target, if any, and is not taken on.
          [relationField(EXAMPLE_TASK_ID, "target")]: EXAMPLE_OTHER_VERSION_ID,
          note: "Example why",
        },
        EDITS_PREFIX,
      ),
    );
    expect(parsed).toEqual({
      ok: true,
      value: {
        ruleKey: "example_rule",
        newRule: null,
        edits: { title: "Example edited title" },
        citations: null,
        relations: [
          {
            candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
            targetRuleVersionId: EXAMPLE_OTHER_VERSION_ID,
          },
        ],
        note: "Example why",
      },
    });
  });

  it("starts a new rule with its regulator and level, citing the analyst's own quotes", () => {
    const parsed = parseDraft(
      form(
        {},
        {
          rule_key: "example_new_rule",
          new_rule: "on",
          "new_rule.regulator": "example_regulator",
          "new_rule.level": "entity",
          citations_mode: "own",
          "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
          "citations.0.quote": "Example clause text",
        },
        EDITS_PREFIX,
      ),
    );
    expect(parsed).toMatchObject({
      ok: true,
      value: {
        ruleKey: "example_new_rule",
        newRule: { regulator: "example_regulator", level: "entity" },
        edits: null,
        citations: [{ clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example clause text" }],
        relations: [],
      },
    });
  });

  it("names every field out of shape before any request", () => {
    const parsed = parseDraft(
      form(
        { title: "" },
        {
          rule_key: "Example Key",
          new_rule: "on",
          "new_rule.regulator": "",
          "new_rule.level": "nowhere",
          [relationField(EXAMPLE_TASK_ID, "take")]: "on",
          [relationField(EXAMPLE_TASK_ID, "target")]: "not-an-id",
        },
        EDITS_PREFIX,
      ),
    );
    expect(parsed).toEqual({
      ok: false,
      formErrors: [],
      errors: {
        rule_key: [
          "A rule key is lower-case letters, digits and underscores, starting with a letter, at most 80 characters.",
        ],
        "new_rule.regulator": ["Enter the new rule's regulator, at most 40 characters."],
        "new_rule.level": ["Choose where the new rule applies."],
        "edits.title": ["Enter a title."],
        [relationField(EXAMPLE_TASK_ID, "target")]: ["Choose the version this relation points at."],
      },
    });
    expect(parseDraft(form({}, {}, EDITS_PREFIX))).toMatchObject({
      ok: false,
      errors: { rule_key: ["Enter the rule's key."] },
    });
  });
});

describe("parseRelations", () => {
  /** A relation candidate id for row n, 1-based: ...0001, ...0002, ... */
  const candidate = (n: number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;

  function rows(count: number, ticked: readonly number[]): FormData {
    const data = new FormData();
    for (let n = 1; n <= count; n += 1) {
      if (ticked.includes(n)) data.set(relationField(candidate(n), "take"), "on");
      data.set(relationField(candidate(n), "target"), n % 2 === 0 ? EXAMPLE_OTHER_VERSION_ID : "");
    }
    return data;
  }

  it("takes a row ticked past the fiftieth: the rows are named by candidate id", () => {
    expect(parseRelations(rows(60, [55]))).toEqual({
      relations: [{ candidateId: candidate(55), targetRuleVersionId: null }],
      errors: {},
    });
    expect(parseRelations(rows(200, [2, 199])).relations).toEqual([
      { candidateId: candidate(2), targetRuleVersionId: EXAMPLE_OTHER_VERSION_ID },
      { candidateId: candidate(199), targetRuleVersionId: null },
    ]);
  });

  it("refuses more rows than one draft takes on, plainly", () => {
    const all = Array.from({ length: 51 }, (_, index) => index + 1);
    expect(parseRelations(rows(60, all)).errors).toEqual({
      relation_candidates: [
        "A draft takes on at most 50 relation candidates at a time; 51 are ticked.",
      ],
    });
    expect(parseRelations(rows(60, all.slice(0, 50))).errors).toEqual({});
  });

  it("skips a name that is not a candidate's id and takes a candidate once", () => {
    const data = rows(2, [1]);
    data.append(relationField(candidate(1), "take"), "on");
    data.set(relationField("not-an-id", "take"), "on");
    data.set(relationField(candidate(2).toUpperCase(), "take"), "on");
    expect(parseRelations(data).relations.map((relation) => relation.candidateId)).toEqual([
      candidate(1),
      candidate(2),
    ]);
  });
});

describe("parseDecision", () => {
  function decision(values: Record<string, string>): FormData {
    const data = new FormData();
    for (const [name, value] of Object.entries(values)) data.set(name, value);
    return data;
  }

  it("approves with the high-impact tag, and returns or rejects with a note", () => {
    expect(parseDecision(decision({ decision: "approve", high_impact: "on" }), false)).toEqual({
      ok: true,
      value: { decision: "approve", note: "", highImpact: true, reason: null },
    });
    expect(
      parseDecision(
        decision({ decision: "return", note: "Example why", high_impact: "on" }),
        false,
      ),
    ).toEqual({
      ok: true,
      value: { decision: "return", note: "Example why", highImpact: false, reason: null },
    });
    expect(
      parseDecision(
        decision({ decision: "reject", note: "Example why", reason: "duplicate" }),
        true,
      ),
    ).toEqual({
      ok: true,
      value: { decision: "reject", note: "Example why", highImpact: false, reason: "duplicate" },
    });
  });

  it("asks for the note, a candidate's reason and a known decision before any request", () => {
    expect(parseDecision(decision({ decision: "return", note: " " }), false)).toEqual({
      ok: false,
      formErrors: [],
      errors: { note: ["Say why: the rulebook keeps the note with the decision."] },
    });
    expect(parseDecision(decision({ decision: "reject", note: "Example why" }), true)).toEqual({
      ok: false,
      formErrors: [],
      errors: { reason: ["Choose why the candidate is rejected."] },
    });
    expect(parseDecision(decision({ decision: "publish" }), false)).toEqual({
      ok: false,
      errors: {},
      formErrors: ["Choose approve, return or reject."],
    });
  });
});

describe("parseClaim", () => {
  it("reads the task id a row names, or nothing that is not one", () => {
    const data = new FormData();
    data.set("task_id", EXAMPLE_TASK_ID.toUpperCase());
    expect(parseClaim(data)).toBe(EXAMPLE_TASK_ID);
    data.set("task_id", "not-a-task");
    expect(parseClaim(data)).toBeNull();
  });
});
