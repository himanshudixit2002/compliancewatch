import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { StatusChip, humaniseStatus } from "./status-chip";

describe("humaniseStatus", () => {
  it("turns snake and kebab case into a sentence", () => {
    expect(humaniseStatus("due_soon")).toBe("Due soon");
    expect(humaniseStatus("not-started")).toBe("Not started");
    expect(humaniseStatus("open")).toBe("Open");
  });
});

describe("StatusChip", () => {
  it("shows the humanised status with a tone dot the text does not depend on", async () => {
    const { container } = render(<StatusChip status="due_soon" tone="warning" />);
    const chip = screen.getByText("Due soon");
    expect(chip.dataset.status).toBe("due_soon");
    expect(chip.dataset.tone).toBe("warning");
    expect(chip.querySelector('[aria-hidden="true"]')?.className).toContain("bg-warning");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("prefers an explicit label and defaults to the neutral tone", () => {
    render(<StatusChip status="live" label="Live now" />);
    const chip = screen.getByText("Live now");
    expect(chip.dataset.tone).toBe("neutral");
  });
});
