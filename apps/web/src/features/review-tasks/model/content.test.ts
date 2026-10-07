import { describe, expect, it } from "vitest";
import { ruleCandidateFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { ruleCandidateDto } from "@/test/review-task-fixture";
import { frequencyLabel, proposalValues, recurrenceWords, versionValues } from "./content";

describe("the form's starting values", () => {
  it("reads a stored draft into the inputs' text", () => {
    const values = versionValues(
      ruleVersionFromDto(
        ruleVersionDto({
          effective_to: "2001-04-01",
          recurrence: { frequency: "weekly", due_day: 1, due_month_offset: 0 },
          obligation_template: { title: "Example", steps: [], due_in_days: 15, evidence_type: "" },
        }),
      ),
    );
    expect(values).toMatchObject({
      effectiveTo: "2001-04-01",
      frequency: "",
      dueDay: "",
      dueMonthOffset: "",
      templateTitle: "Example",
      templateSteps: "",
      templateDueInDays: "15",
      templateEvidence: "",
    });
    expect(values.specification).toEqual(ruleVersionDto().specification);
  });

  it("starts a draft from the proposal, each field it does not map left empty", () => {
    const values = proposalValues(
      ruleCandidateFromDto(
        ruleCandidateDto({
          proposed: {
            ...ruleCandidateDto().proposed,
            title: null,
            summary: null,
            effective_from: null,
            obligation_template: null,
            recurrence: { frequency: "quarterly", due_day: 18, due_month_offset: 1 },
          },
        }),
      ).proposed,
    );
    expect(values).toMatchObject({
      title: "",
      summary: "",
      effectiveFrom: "",
      effectiveTo: "",
      frequency: "quarterly",
      dueDay: "18",
      dueMonthOffset: "1",
      templateTitle: "",
      templateDueInDays: "",
      todo: "",
    });
  });
});

describe("the words", () => {
  it("words each frequency, and one it does not know as sent", () => {
    expect(frequencyLabel("half_yearly")).toBe("Half-yearly");
    expect(frequencyLabel("example_cadence")).toBe("Example cadence");
    expect(recurrenceWords({ frequency: "monthly", dueDay: null, dueMonthOffset: null })).toBe(
      "Monthly, due on day - of the month after the period",
    );
  });
});
