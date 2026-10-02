import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { StatCard } from "./stat-card";

describe("StatCard", () => {
  it("pairs the label with its value and carries the tone", async () => {
    const { container } = render(
      <StatCard label="Overdue" value={3} tone="danger" hint="Past due" />,
    );
    const card = container.querySelector("[data-slot='stat-card']");
    expect(card?.getAttribute("data-tone")).toBe("danger");
    expect(screen.getByText("Overdue").tagName).toBe("DT");
    expect(screen.getByText("3").tagName).toBe("DD");
    expect(screen.getByText("Past due")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("defaults to the neutral tone and leaves the hint out", () => {
    const { container } = render(<StatCard label="Total" value="12" />);
    expect(container.querySelector("[data-slot='stat-card']")?.getAttribute("data-tone")).toBe(
      "neutral",
    );
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });
});
