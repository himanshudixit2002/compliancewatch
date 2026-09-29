import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScreenStatusChip } from "./screen-status-chip";

describe("ScreenStatusChip", () => {
  it("shows the status in words with the matching tone", () => {
    render(<ScreenStatusChip status="waiting" />);
    const chip = screen.getByText("Waiting for a backend");
    expect(chip.getAttribute("data-tone")).toBe("warning");
    expect(chip.getAttribute("data-status")).toBe("waiting");
  });

  it("uses success for live, info for ready and neutral for planned", () => {
    const { rerender } = render(<ScreenStatusChip status="live" />);
    expect(screen.getByText("Available").getAttribute("data-tone")).toBe("success");
    rerender(<ScreenStatusChip status="ready" />);
    expect(screen.getByText("Ready to build").getAttribute("data-tone")).toBe("info");
    rerender(<ScreenStatusChip status="planned" />);
    expect(screen.getByText("No backend scheduled").getAttribute("data-tone")).toBe("neutral");
  });
});
