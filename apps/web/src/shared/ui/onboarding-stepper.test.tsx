import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { OnboardingStepper } from "./onboarding-stepper";

describe("OnboardingStepper", () => {
  it("names the four steps and marks the current one", async () => {
    const { container } = render(<OnboardingStepper current="questions" />);
    const nav = screen.getByRole("navigation", { name: "Onboarding steps" });
    expect([...nav.querySelectorAll("li")].map((item) => item.dataset.state)).toEqual([
      "done",
      "done",
      "current",
      "upcoming",
    ]);
    expect(nav.querySelector("[aria-current='step']")?.textContent).toContain("Questions");
    expect(screen.getByText("Step 3 of 4")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
