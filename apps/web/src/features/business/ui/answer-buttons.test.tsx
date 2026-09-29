import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { AnswerButtons } from "./answer-buttons";

describe("AnswerButtons", () => {
  it("submits the chosen state with the form", async () => {
    const user = userEvent.setup();
    const states: (string | null)[] = [];
    const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
      states.push(submitter?.value ?? null);
    });
    const { container } = render(
      <form aria-label="Example answer" onSubmit={onSubmit}>
        <AnswerButtons id="q" />
      </form>,
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Not sure" }));
    await user.click(screen.getByRole("button", { name: "Does not apply" }));
    expect(states).toEqual(["known", "unsure", "not_applicable"]);
    for (const button of screen.getAllByRole("button")) {
      expect(button.getAttribute("name")).toBe("state");
    }
    const notApplicable = screen.getByRole("button", { name: "Does not apply" });
    expect(notApplicable.getAttribute("aria-describedby")).toBe("q-not-applicable-hint");
    expect(screen.getByText(/opens a review task an analyst will look at/).id).toBe(
      "q-not-applicable-hint",
    );
    expect(screen.getByRole("group", { name: "Answer" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("disables every button and marks it busy while pending", () => {
    render(<AnswerButtons id="q" pending name="answer_state" />);
    expect(screen.getByRole("button", { name: "Saving" })).toBeDefined();
    for (const button of screen.getAllByRole("button")) {
      expect(button.hasAttribute("disabled")).toBe(true);
      expect(button.getAttribute("aria-busy")).toBe("true");
      expect(button.getAttribute("name")).toBe("answer_state");
    }
  });

  it("offers Save alone where only a value makes sense", () => {
    render(<AnswerButtons id="q" valueOnly />);
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Save"]);
    expect(screen.queryByText(/review task/)).toBeNull();
  });
});
