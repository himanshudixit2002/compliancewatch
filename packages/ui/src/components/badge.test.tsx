import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { TONES } from "../tokens";
import { Badge } from "./badge";

describe("Badge", () => {
  it("renders its children with the neutral tone by default", async () => {
    const { container } = render(<Badge>Preview</Badge>);
    const badge = screen.getByText("Preview");
    expect(badge.tagName).toBe("SPAN");
    expect(badge.dataset.tone).toBe("neutral");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it.each(TONES)("applies the %s tone through token classes", (tone) => {
    render(<Badge tone={tone}>Label</Badge>);
    const badge = screen.getByText("Label");
    expect(badge.dataset.tone).toBe(tone);
    if (tone !== "neutral") {
      expect(badge.className).toContain(`bg-${tone}`);
      expect(badge.className).toContain(`text-${tone}-fg`);
    }
  });

  it("renders the child element when asChild is set", () => {
    render(
      <Badge asChild tone="info">
        <a href="/x">Linked</a>
      </Badge>,
    );
    const link = screen.getByRole("link", { name: "Linked" });
    expect(link.dataset.tone).toBe("info");
  });
});
