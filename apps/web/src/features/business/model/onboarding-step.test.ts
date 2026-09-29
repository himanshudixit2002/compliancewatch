import { describe, expect, it } from "vitest";
import { businessFromDto, onboardingFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import type { Onboarding, Question } from "@/entities/business/types";
import {
  BUSINESS_DTO,
  ENTITY_ID,
  ONBOARDING_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
} from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import {
  doneSummaryView,
  questionStepView,
  summaryViewedEvent,
  type OnboardingState,
} from "./onboarding-step";
import { skipKey } from "./questions";

const base = onboardingFromDto(ONBOARDING_DTO);

function state(
  next: Partial<Question> | null,
  extra: Partial<OnboardingState> = {},
): OnboardingState {
  const onboarding: Onboarding =
    next === null
      ? { ...base, next: null, complete: true }
      : { ...base, next: { ...(base.next as Question), ...next } };
  return {
    business: businessFromDto(BUSINESS_DTO),
    onboarding,
    ontology: ontologyFixture(),
    tasks: [
      reviewTaskFromDto(REVIEW_TASK_DTO),
      reviewTaskFromDto({ ...REVIEW_TASK_DTO, id: "closed-task", open: false }),
    ],
    ...extra,
  };
}

describe("questionStepView", () => {
  it("words the next question with its node, the progress and the open review tasks", () => {
    const view = questionStepView(state({}), new Set());
    expect(view.businessId).toBe(ENTITY_ID);
    expect(view.progress.text).toBe("4 of 8 answered");
    expect(view.unsureCount).toBe(1);
    expect(view.question).toMatchObject({
      nodeId: REGISTRATION_ID,
      key: "example_flag",
      asOfFy: null,
      heading: "Example question about example_flag?",
      help: "Example definition of example_flag.",
      about: "About the registration 29ABCDE1234F1Z5 (Example registration).",
      yearText: null,
      wasUnsure: false,
      type: "boolean",
    });
    expect(view.question?.attribute?.key).toBe("example_flag");
    expect(view.reviewTasks.map((row) => row.id)).toEqual([REVIEW_TASK_DTO.id]);
    expect(view.reviewTasks[0]?.nodeName).toBe("29ABCDE1234F1Z5 (Example registration)");
    expect(view.saved).toBeNull();
  });

  it("names the year of a per-year question and says when it was unsure before", () => {
    const view = questionStepView(
      state({
        nodeId: ENTITY_ID,
        level: "entity",
        key: "example_band",
        state: "unsure",
        perFinancialYear: true,
        asOfFy: "2000-01",
        type: "ordered_enum",
        question: "",
        help: "Example service help.",
      }),
      new Set(),
    );
    expect(view.question).toMatchObject({
      heading: "Example band",
      help: "Example service help.",
      about: "About Example business (PAN ABCDE1234F).",
      yearText: "The answer is for the financial year 2000-01.",
      wasUnsure: true,
    });
  });

  it("keeps a question whose type has no control, without an attribute", () => {
    const view = questionStepView(
      state({ key: "example_new", type: "polygon", help: "" }),
      new Set(),
    );
    expect(view.question?.attribute).toBeUndefined();
    expect(view.question?.help).toBe("");
  });

  it("says what was saved, and whether it opened a review task", () => {
    expect(questionStepView(state({}), new Set(), "example_flag").saved).toEqual({
      label: "Example flag",
      reviewTaskOpened: true,
    });
    expect(questionStepView(state({}), new Set(), "example_kind").saved).toEqual({
      label: "Example kind",
      reviewTaskOpened: false,
    });
    expect(questionStepView(state({}), new Set(), "").saved).toBeNull();
  });

  it("has no question when everything open was skipped", () => {
    const skipped = new Set([
      skipKey(REGISTRATION_ID, "example_flag"),
      skipKey(ENTITY_ID, "example_count"),
      skipKey(REGISTRATION_ID, "example_since"),
    ]);
    expect(questionStepView(state({}), skipped).question).toBeNull();
  });
});

describe("doneSummaryView", () => {
  it("counts the checklist, lists what is unsure or missing and the open tasks", () => {
    const view = doneSummaryView(state(null));
    expect(view).toMatchObject({
      businessId: ENTITY_ID,
      businessName: "Example business",
      pan: "ABCDE1234F",
      gstins: ["29ABCDE1234F1Z5"],
      counts: { known: 3, not_applicable: 1, unsure: 1, missing: 1 },
      unsure: [
        {
          id: skipKey(ENTITY_ID, "example_count"),
          label: "Example count",
          node: "Example business (PAN ABCDE1234F)",
        },
      ],
      missing: [{ id: skipKey(REGISTRATION_ID, "example_since"), label: "Example since" }],
    });
    expect(view.reviewTasks).toHaveLength(1);
    expect(view.progress.complete).toBe(true);
  });

  it("gives the summary's product event as counts only", () => {
    const view = doneSummaryView(state(null));
    expect(summaryViewedEvent(view)).toEqual({
      name: "onboarding_summary_viewed",
      properties: {
        complete: true,
        answered: view.progress.answered,
        total: view.progress.total,
        unsure: 1,
        open_review_tasks: 1,
      },
    });
  });
});
