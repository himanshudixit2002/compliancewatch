import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { HighlightMark } from "./highlight-mark";

describe("HighlightMark", () => {
  it("marks the span and tells screen readers where it starts and ends", async () => {
    const { container } = render(
      <p>
        Example clause text with <HighlightMark>a marked span</HighlightMark> inside it.
      </p>,
    );
    const mark = container.querySelector("mark");
    expect(mark?.textContent).toBe("a marked span");
    expect(mark?.dataset.slot).toBe("highlight-mark");
    expect(mark?.className).toContain("underline");
    expect(container.textContent).toBe(
      "Example clause text with Highlight starts: a marked span Highlight ends. inside it.",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("takes its own labels and classes", () => {
    render(
      <HighlightMark startLabel="Quote starts" endLabel="Quote ends" className="px-1">
        quoted
      </HighlightMark>,
    );
    expect(screen.getByText("Quote starts:", { exact: false })).toBeDefined();
    expect(screen.getByText("Quote ends.", { exact: false })).toBeDefined();
    expect(screen.getByText("quoted").className).toContain("px-1");
  });
});
