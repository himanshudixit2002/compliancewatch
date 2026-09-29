import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VisuallyHidden } from "./visually-hidden";

describe("VisuallyHidden", () => {
  it("keeps the text in the document with the sr-only class", () => {
    render(<VisuallyHidden>Only for screen readers</VisuallyHidden>);
    const el = screen.getByText("Only for screen readers");
    expect(el.className).toContain("sr-only");
    expect(el.dataset.slot).toBe("visually-hidden");
  });
});
