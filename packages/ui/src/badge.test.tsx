import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "./badge";

describe("Badge", () => {
  it("renders its children with the neutral tone by default", () => {
    render(<Badge>Preview</Badge>);
    const badge = screen.getByText("Preview");
    expect(badge.tagName).toBe("SPAN");
    expect(badge.getAttribute("data-tone")).toBe("neutral");
  });

  it("applies the requested tone", () => {
    render(<Badge tone="danger">Overdue</Badge>);
    expect(screen.getByText("Overdue").getAttribute("data-tone")).toBe("danger");
  });
});
