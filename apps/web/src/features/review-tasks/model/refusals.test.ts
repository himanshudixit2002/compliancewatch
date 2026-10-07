import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import type { ApiError } from "@/server/result";
import { REVIEW_PROBLEMS, isRefusal, listedProblems, refusalState } from "./refusals";

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

  it("tells a refusal by its slug", () => {
    expect(isRefusal(refusal(REVIEW_PROBLEMS.closed, 409), REVIEW_PROBLEMS.closed)).toBe(true);
    expect(isRefusal(refusal(REVIEW_PROBLEMS.closed, 409), REVIEW_PROBLEMS.claimed)).toBe(false);
  });
});
