import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ValueStateChip } from "./value-state-chip";

describe("ValueStateChip", () => {
  it("says the state in words with a tone per state", async () => {
    const { container } = render(
      <p>
        <ValueStateChip state="known" />
        <ValueStateChip state="unsure" />
        <ValueStateChip state="not_applicable" className="ml-2" />
      </p>,
    );
    const chips = [...container.querySelectorAll("[data-slot='status-chip']")];
    expect(chips.map((chip) => [chip.textContent, chip.getAttribute("data-tone")])).toEqual([
      ["Known", "success"],
      ["Not sure", "warning"],
      ["Does not apply", "neutral"],
    ]);
    expect(screen.getByText("Does not apply").className).toContain("ml-2");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
