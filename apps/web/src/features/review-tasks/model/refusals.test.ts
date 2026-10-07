import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import type { ApiError } from "@/server/result";
import { EXAMPLE_OTHER_VERSION_ID, EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { EXAMPLE_RELATION_CANDIDATE_ID, EXAMPLE_TASK_ID } from "@/test/review-task-fixture";
import { relationField } from "../ui/form-shared";
import {
  REVIEW_PROBLEMS,
  isRefusal,
  listedProblems,
  onRelationRows,
  refusalState,
  relationRowErrors,
  type SentRelation,
} from "./refusals";

function refusal(slug: string, status: number, detail?: string): ApiError {
  return {
    kind: status === 409 ? "conflict" : status === 422 ? "validation" : "unavailable",
    status,
    requestId: "example-request",
    message: `Example title of ${slug}`,
    problem: {
      type: `${PROBLEM_TYPE_PREFIX}${slug}`,
      title: `Example title of ${slug}`,
      status,
      ...(detail === undefined ? {} : { detail }),
    },
  };
}

describe("refusalState", () => {
  it("says a known refusal plainly, keeping the type, the correlation id and the detail it does not replace", () => {
    expect(
      refusalState(refusal("rulebook-overlapping-version", 409, "Example overlap detail")),
    ).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}rulebook-overlapping-version`,
        title: "Two versions of this rule would be in force on the same day",
        detail: "Example overlap detail",
        correlationId: "example-request",
      },
    });
    expect(refusalState(refusal("rulebook-duplicate-approver", 409))).toMatchObject({
      problem: {
        title: "A different reviewer must approve",
        detail:
          "You approved this round already: a high-impact version needs two different approvers.",
      },
    });
    expect(refusalState(refusal("rulebook-review-token-invalid", 401))).toMatchObject({
      problem: {
        title: "The web app's review token is wrong",
        detail: expect.stringContaining("An operator must set it") as string,
      },
    });
    expect(refusalState(refusal("rulebook-reviews-disabled", 503))).toMatchObject({
      problem: { title: "Reviews are switched off on the rulebook" },
    });
  });

  it("lists every problem of an incomplete draft, one per line", () => {
    const state = refusalState(
      refusal(REVIEW_PROBLEMS.draftIncomplete, 422, "title: missing; effective_from: missing"),
    );
    expect(state).toMatchObject({
      problem: { title: "The draft is incomplete" },
      formErrors: ["title: missing", "effective_from: missing"],
    });
  });

  it("passes a refusal it does not know on as the rulebook worded it, with its field errors", () => {
    const error: ApiError = {
      ...refusal("rulebook-example", 422, "Example detail"),
      fieldErrors: { title: ["Example field message"] },
    };
    expect(refusalState(error)).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}rulebook-example`,
        title: "Example title of rulebook-example",
        detail: "Example detail",
        correlationId: "example-request",
      },
      fieldErrors: { title: ["Example field message"] },
    });
    expect(listedProblems(error)).toEqual([]);
  });

  it("words a content refusal of an edit and lists each problem on a line", () => {
    const state = refusalState(
      refusal(
        REVIEW_PROBLEMS.invariant,
        422,
        "specification: example_kind = nowhere: not an option; effective_to must be after effective_from",
      ),
      { step: "edit" },
    );
    expect(state).toMatchObject({
      problem: {
        title: "The rulebook refused the draft's content",
        detail:
          "Nothing was saved. Each problem it found is listed below: fix the fields it names, then save again.",
      },
      formErrors: [
        "specification: example_kind = nowhere: not an option",
        "effective_to must be after effective_from",
      ],
    });
    expect(
      refusalState(refusal(REVIEW_PROBLEMS.invariant, 422, "Example rule"), { step: "decide" }),
    ).toMatchObject({
      problem: { title: "The rulebook refused the decision" },
      formErrors: ["Example rule"],
    });
    expect(refusalState(refusal(REVIEW_PROBLEMS.invariant, 422, "Example"))).toMatchObject({
      problem: { title: "The rulebook refused the request" },
    });
  });

  it("says a draft into another regulator's rule and the rules of a decision in their own words", () => {
    expect(
      refusalState(
        refusal(
          REVIEW_PROBLEMS.invariant,
          422,
          "rule example_rule is example_a's and the candidate example_b's: a candidate's draft belongs to a rule of its own regulator",
        ),
        { step: "draft" },
      ),
    ).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}invariant-violation`,
        title: "The rule is another regulator's",
        detail:
          "A candidate's draft goes into a rule of the candidate's own regulator: choose one of its rules, or start a new rule. Nothing was stored.",
        correlationId: "example-request",
      },
    });
    const decide = (detail: string) =>
      refusalState(refusal(REVIEW_PROBLEMS.invariant, 422, detail), { step: "decide" });
    expect(decide("a return says why in its note")).toMatchObject({
      problem: { title: "A return or a rejection needs a note saying why" },
    });
    expect(decide("high_impact is raised with an approval")).toMatchObject({
      problem: { title: "Only an approval marks a version high impact" },
    });
    expect(decide("a candidate's rejection names its reason: not_a_rule, duplicate")).toMatchObject(
      { problem: { title: "A candidate's rejection needs its reason" } },
    );
    expect(decide("only a candidate task's rejection takes a reason")).toMatchObject({
      problem: { title: "Only a candidate's rejection takes a reason" },
    });
    expect(decide("a reason is given with a rejection").status).toBe("error");
    expect(decide("a reason is given with a rejection")).not.toHaveProperty("formErrors");
  });

  it("says each relation refusal plainly and puts it on the row its detail names", () => {
    const other = "00000000-0000-4000-8000-0000000000cd";
    const sent: SentRelation[] = [
      {
        candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
        targetRuleVersionId: EXAMPLE_OTHER_VERSION_ID,
        relation: "supersedes",
        targetName: "EXAMPLE-1",
      },
      {
        candidateId: other,
        targetRuleVersionId: null,
        relation: "refers_to",
        targetName: "FORM X",
      },
    ];
    const take = (id: string) => relationField(id, "take");
    const target = (id: string) => relationField(id, "target");
    expect(
      refusalState(
        refusal(
          "rulebook-relation-candidate-closed",
          409,
          `candidate ${EXAMPLE_RELATION_CANDIDATE_ID} is approved`,
        ),
        { step: "draft", relations: sent },
      ),
    ).toMatchObject({
      problem: { title: "A relation candidate the draft takes on was decided meanwhile" },
      fieldErrors: {
        [take(EXAMPLE_RELATION_CANDIDATE_ID)]: [
          "This relation candidate is not open on the candidate's document any more: untick it.",
        ],
      },
    });
    expect(
      relationRowErrors(
        refusal(
          "rulebook-relation-candidate-not-found",
          404,
          `relation candidate ${other} does not exist`,
        ),
        sent,
      ),
    ).toEqual({
      [take(other)]: [
        "This relation candidate is not open on the candidate's document any more: untick it.",
      ],
    });
    expect(
      relationRowErrors(
        refusal("rulebook-rule-version-not-found", 404, EXAMPLE_OTHER_VERSION_ID),
        sent,
      ),
    ).toEqual({
      [target(EXAMPLE_RELATION_CANDIDATE_ID)]: [expect.stringMatching(/no such version/)],
    });
    expect(
      relationRowErrors(
        refusal(
          "rulebook-supersession-cycle",
          409,
          `${EXAMPLE_OTHER_VERSION_ID} -> ${EXAMPLE_VERSION_ID} -> ${EXAMPLE_OTHER_VERSION_ID}`,
        ),
        sent,
      ),
    ).toEqual({ [target(EXAMPLE_RELATION_CANDIDATE_ID)]: [expect.stringMatching(/cycle/)] });
    expect(
      relationRowErrors(
        refusal("rulebook-relation-target-unresolved", 422, "form 'FORM X' is not aligned yet"),
        sent,
      ),
    ).toEqual({ [target(other)]: [expect.stringMatching(/not aligned/)] });
    expect(
      relationRowErrors(
        refusal(
          "rulebook-target-version-required",
          422,
          "refers_to with this candidate needs the target rule version",
        ),
        sent,
      ),
    ).toEqual({ [target(other)]: ["Choose the version this relation points at."] });
    // A detail that names no row leaves the refusal on the form.
    expect(relationRowErrors(refusal("rulebook-supersession-cycle", 409, "Example"), sent)).toEqual(
      {},
    );
    expect(
      refusalState(refusal("rulebook-relation-target-unresolved", 422, "Example")),
    ).toMatchObject({ problem: { title: "A relation's target is not aligned to an entity" } });
    expect(
      refusalState(refusal("rulebook-supersession-cycle", 409, "Example a -> b")),
    ).toMatchObject({
      problem: { title: "The supersession would form a cycle", detail: "Example a -> b" },
    });
    expect(refusalState(refusal("rulebook-rule-version-not-found", 404))).toMatchObject({
      problem: { title: "A version the request names is not in the rulebook" },
    });
    expect(refusalState(refusal("rulebook-relation-candidate-not-found", 404))).toMatchObject({
      problem: { title: "A relation candidate the draft takes on is not in the rulebook" },
    });
  });

  it("moves the rulebook's field errors on the relation list onto the rows by the order sent", () => {
    expect(
      onRelationRows(
        {
          status: "error",
          fieldErrors: {
            "relation_candidates.1.target_rule_version_id": ["Example target error"],
            "relation_candidates.0.candidate_id": ["Example id error"],
            "relation_candidates.7.target_rule_version_id": ["Example stray error"],
            rule_key: ["Example key error"],
          },
        },
        [{ candidateId: EXAMPLE_RELATION_CANDIDATE_ID }, { candidateId: EXAMPLE_TASK_ID }],
      ),
    ).toEqual({
      status: "error",
      fieldErrors: {
        [relationField(EXAMPLE_TASK_ID, "target")]: ["Example target error"],
        [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: ["Example id error"],
        "relation_candidates.7.target_rule_version_id": ["Example stray error"],
        rule_key: ["Example key error"],
      },
    });
    expect(onRelationRows({ status: "ok", value: 1 }, [])).toEqual({ status: "ok", value: 1 });
  });

  it("tells a refusal by its slug", () => {
    expect(isRefusal(refusal(REVIEW_PROBLEMS.closed, 409), REVIEW_PROBLEMS.closed)).toBe(true);
    expect(isRefusal(refusal(REVIEW_PROBLEMS.closed, 409), REVIEW_PROBLEMS.claimed)).toBe(false);
  });
});
