import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { TONES } from "../tokens";
import { Banner } from "./banner";
import { Button } from "./button";

describe("Banner", () => {
  it("is a polite status by default with a title, body and action", async () => {
    const { container } = render(
      <Banner tone="info" title="Example title" action={<Button variant="link">Undo</Button>}>
        Example body
      </Banner>,
    );
    const banner = screen.getByRole("status");
    expect(banner.dataset.tone).toBe("info");
    expect(banner.textContent).toContain("Example title");
    expect(banner.textContent).toContain("Example body");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("is an alert when the tone is danger", () => {
    render(<Banner tone="danger">Something failed</Banner>);
    expect(screen.getByRole("alert").dataset.tone).toBe("danger");
  });

  it.each(TONES)("renders the %s tone", (tone) => {
    const { container } = render(<Banner tone={tone}>Text</Banner>);
    expect(container.querySelector('[data-slot="banner"]')?.getAttribute("data-tone")).toBe(tone);
  });
});
