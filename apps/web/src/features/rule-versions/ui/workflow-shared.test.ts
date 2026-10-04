import { describe, expect, it } from "vitest";
import { lifecycleFromDto, publicationFromDto } from "@/entities/rule-version/mappers";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_ANALYST_ID,
  lifecycleDto,
  publicationDto,
} from "@/test/rule-version-fixture";
import { stepResult } from "../model/workflow";
import { hasRound, roundSummary, stepDescription, stepLabel, stepOutcome } from "./workflow-shared";

describe("roundSummary", () => {
  it("marks the session's own approval and says a second approver is needed", () => {
    expect(roundSummary(lifecycleFromDto(lifecycleDto()), EXAMPLE_ANALYST_ID)).toEqual({
      approvers: [{ userId: EXAMPLE_ANALYST_ID, you: true }],
      count: 1,
      required: 2,
      waitingForAnother: true,
    });
  });

  it("waits for nobody before the first approval and once the round is complete", () => {
    expect(
      roundSummary(lifecycleFromDto(lifecycleDto({ approved_by: [] })), EXAMPLE_ANALYST_ID)
        .waitingForAnother,
    ).toBe(false);
    const complete = roundSummary(
      lifecycleFromDto(
        lifecycleDto({
          status: "approved",
          approved_by: [EXAMPLE_ANALYST_ID, EXAMPLE_OTHER_ANALYST_ID],
        }),
      ),
      EXAMPLE_OTHER_ANALYST_ID,
    );
    expect(complete).toMatchObject({ count: 2, waitingForAnother: false });
    expect(complete.approvers.map((approver) => approver.you)).toEqual([false, true]);
  });

  it("has a round to report on only under review, approved or published", () => {
    expect(hasRound(lifecycleFromDto(lifecycleDto()))).toBe(true);
    expect(hasRound(lifecycleFromDto(lifecycleDto({ status: "draft" })))).toBe(false);
  });
});

describe("stepOutcome", () => {
  const outcome = (step: Parameters<typeof stepResult>[0], overrides = {}) =>
    stepOutcome(stepResult(step, lifecycleFromDto(lifecycleDto(overrides))), EXAMPLE_ANALYST_ID);

  it("says what each step did", () => {
    expect(outcome("submit")).toBe(
      "Submitted for review as high impact: a new review round started, and it needs two different approvers.",
    );
    expect(outcome("submit", { high_impact: false })).toBe(
      "Submitted for review: a new review round started.",
    );
    expect(outcome("approve")).toBe(
      "Your approval is recorded: 1 of 2 approvals. The version stays in review until the round is complete.",
    );
    expect(outcome("approve", { status: "approved", required_approvals: 1 })).toBe(
      "Approved: 1 of 1 approvals. The version can be published.",
    );
    expect(outcome("return")).toBe("Returned to draft: the round's approvals no longer count.");
    expect(outcome("withdraw")).toBe("Withdrawn from today.");
    expect(
      stepOutcome(stepResult("publish", publicationFromDto(publicationDto())), EXAMPLE_ANALYST_ID),
    ).toBe("Published. It replaces 1 versions and moves 0 due dates, as its relations say.");
  });

  it("names each step and what its dialog records", () => {
    expect(stepLabel("return")).toBe("Return to draft");
    expect(stepDescription("withdraw")).toContain("The reason is recorded with the step.");
  });
});
