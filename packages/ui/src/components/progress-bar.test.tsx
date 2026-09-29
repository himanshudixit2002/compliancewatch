import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { ProgressBar } from "./progress-bar";

describe("ProgressBar", () => {
  it("is a progressbar named by its label, with its range and value text", async () => {
    const { container } = render(
      <ProgressBar label="Example progress" value={4} max={17} valueText="4 of 17 done" />,
    );
    const bar = screen.getByRole("progressbar", { name: "Example progress" });
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("17");
    expect(bar.getAttribute("aria-valuenow")).toBe("4");
    expect(bar.getAttribute("aria-valuetext")).toBe("4 of 17 done");
    expect(screen.getByText("4 of 17 done")).toBeDefined();
    const fill = container.querySelector<HTMLElement>("[data-slot='progress-bar-fill']");
    expect(fill?.style.width).toBe("24%");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("clamps the value to the range and defaults the range to 100", () => {
    const { container, rerender } = render(<ProgressBar label="Example" value={140} />);
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-valuenow")).toBe("100");
    expect(bar.getAttribute("aria-valuetext")).toBeNull();
    rerender(<ProgressBar label="Example" value={-3} max={10} />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
    const fill = () => container.querySelector<HTMLElement>("[data-slot='progress-bar-fill']");
    expect(fill()?.style.width).toBe("0%");
    // Nothing to do counts as done.
    rerender(<ProgressBar label="Example" value={0} max={0} />);
    expect(fill()?.style.width).toBe("100%");
  });
});
