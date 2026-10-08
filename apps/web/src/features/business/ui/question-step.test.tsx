import { render, screen, waitFor } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { businessFromDto, onboardingFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import {
  BUSINESS_DTO,
  ENTITY_ID,
  ONBOARDING_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
} from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { questionStepView, type OnboardingState } from "../model/onboarding-step";
import { QuestionStep } from "./question-step";

const FIELDS = {
  businessId: "business_id",
  nodeId: "node_id",
  key: "key",
  asOfFy: "as_of_fy",
  value: "value",
};

function state(tasks = [reviewTaskFromDto(REVIEW_TASK_DTO)]): OnboardingState {
  return {
    business: businessFromDto(BUSINESS_DTO),
    onboarding: onboardingFromDto(ONBOARDING_DTO),
    ontology: ontologyFixture(),
    tasks,
  };
}

const action = vi.fn(async (): Promise<ActionState> => ({ status: "idle" }));

describe("QuestionStep", () => {
  it("asks one question as the h1 with the progress, the answers and the open tasks", async () => {
    const { container } = render(
      <main>
        <QuestionStep
          view={questionStepView(state(), new Set())}
          action={action}
          fields={FIELDS}
          doneHref="/done"
        />
      </main>,
    );
    const steps = screen.getByRole("navigation", { name: "Onboarding steps" });
    expect(steps.querySelector("[aria-current='step']")?.textContent).toContain("Questions");
    const bar = screen.getByRole("progressbar", {
      name: "Onboarding progress for Example business",
    });
    expect(bar.getAttribute("aria-valuetext")).toBe("4 of 8 answered");
    expect(
      screen.getByRole("heading", { level: 1, name: "Example question about example_flag?" }),
    ).toBeDefined();
    expect(
      screen.getByText("About the registration 29ABCDE1234F1Z5 (Example registration)."),
    ).toBeDefined();
    expect(
      screen.getByRole("radiogroup", { name: "Example question about example_flag?" }),
    ).toBeDefined();
    const hidden = container.querySelector<HTMLInputElement>("input[name='node_id']");
    expect(hidden?.value).toBe(REGISTRATION_ID);
    expect(container.querySelector<HTMLInputElement>("input[name='business_id']")?.value).toBe(
      ENTITY_ID,
    );
    expect(screen.getByText(/You answered Not sure to 1 of the questions/)).toBeDefined();
    expect(screen.getByRole("table", { name: "Open review tasks on this business" })).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Stop here and see the summary" }).getAttribute("href"),
    ).toBe("/done");
    await waitFor(() => expect(document.activeElement).toBe(document.body));
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("names what was saved, moves focus to the new question and says when none is open", async () => {
    const { container } = render(
      <main>
        <QuestionStep
          view={questionStepView(state([]), new Set(), "example_kind")}
          action={action}
          fields={FIELDS}
          doneHref="/done"
        />
      </main>,
    );
    expect(screen.getByText("Saved your answer about Example kind.")).toBeDefined();
    await waitFor(() => expect(document.activeElement?.tagName).toBe("H1"));
    expect(screen.getByText("No review task is open on this business.")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when an answer opened a review task and when a question was unsure before", () => {
    const view = questionStepView(state(), new Set(), "example_flag");
    render(
      <QuestionStep
        view={{
          ...view,
          question: view.question && {
            ...view.question,
            wasUnsure: true,
            yearText: "The answer is for the financial year 2000-01.",
          },
        }}
        action={action}
        fields={FIELDS}
        doneHref="/done"
      />,
    );
    expect(screen.getByText(/It opened a review task/)).toBeDefined();
    expect(screen.getByText(/You answered Not sure to this before/)).toBeDefined();
    expect(screen.getByText(/The answer is for the financial year 2000-01\./)).toBeDefined();
  });

  it("explains a question it cannot draw, and the end of the questions", () => {
    const view = questionStepView(state(), new Set());
    const { rerender } = render(
      <QuestionStep
        view={{
          ...view,
          question: view.question && { ...view.question, attribute: undefined, type: "polygon" },
        }}
        action={action}
        fields={FIELDS}
        doneHref="/done"
      />,
    );
    expect(screen.getByText("This question cannot be shown here yet")).toBeDefined();
    expect(screen.getByText(/type polygon/)).toBeDefined();
    rerender(
      <QuestionStep
        view={{ ...view, question: null }}
        action={action}
        fields={FIELDS}
        doneHref="/done"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Nothing left to ask" })).toBeDefined();
    expect(screen.getByRole("link", { name: "See the summary" }).getAttribute("href")).toBe(
      "/done",
    );
  });
});
