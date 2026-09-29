import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Stepper } from "./stepper";

const steps = [
  { id: "consent", label: "Consent" },
  { id: "business", label: "Business", description: "Registration" },
  { id: "questions", label: "Questions" },
];

describe("Stepper", () => {
  it("marks the current step and states the progress", async () => {
    const { container } = render(<Stepper steps={steps} current={1} />);
    expect(screen.getByRole("navigation", { name: "Progress" })).toBeDefined();
    expect(screen.getByText("Step 2 of 3")).toBeDefined();
    const items = screen.getAllByRole("listitem");
    expect(items[0]?.dataset.state).toBe("done");
    expect(items[1]?.dataset.state).toBe("current");
    expect(items[1]?.getAttribute("aria-current")).toBe("step");
    expect(items[2]?.dataset.state).toBe("upcoming");
    expect(items[2]?.getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("Registration")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("caps the progress text at the last step", () => {
    render(<Stepper steps={steps} current={5} label="Onboarding" />);
    expect(screen.getByText("Step 3 of 3")).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Onboarding" })).toBeDefined();
  });
});
