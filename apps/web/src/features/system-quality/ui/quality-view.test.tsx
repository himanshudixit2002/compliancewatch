import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { QualityMetric } from "../model/quality";
import { SystemQualityView } from "./quality-view";

const METRICS: QualityMetric[] = [
  {
    id: "q_recall",
    name: "Context recall",
    description: "Share of gold clauses present in the retrieved set.",
    value: 0.934,
    target: 0.92,
  },
  {
    id: "q_grounded",
    name: "Grounded-answer rate",
    description: "Answers whose every claim is supported by a cited clause.",
    value: 0.951,
    target: 0.97,
  },
  {
    id: "q_citation",
    name: "Citation correctness",
    description: "Cited spans that match the clause text.",
    value: 0.98,
    target: 0.98,
  },
  {
    id: "q_refusal",
    name: "Refusal accuracy",
    description: "Unsupported questions answered as not covered.",
    value: null,
    target: 0.95,
  },
];

function figures(container: HTMLElement): Record<string, { value: string; tone: string }> {
  const cards = [...container.querySelectorAll<HTMLElement>("[data-slot='stat-card']")];
  return Object.fromEntries(
    cards.map((card) => [
      card.querySelector("dt")?.textContent ?? "",
      {
        value: card.querySelector("dd")?.textContent ?? "",
        tone: card.getAttribute("data-tone") ?? "",
      },
    ]),
  );
}

function metricRow(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-metric='${id}']`) as HTMLElement;
}

describe("SystemQualityView", () => {
  it("counts where the measures stand and shows each against its target", async () => {
    const { container } = render(
      <SystemQualityView metrics={METRICS} measuredAt="2026-10-01T18:30:00Z" />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Quality numbers" })).toBeDefined();
    expect(
      screen.getByText(
        `How our answers and rules measure up against the targets we hold ourselves to, from the evaluation run of ${formatDateTime("2026-10-01T18:30:00Z")}.`,
      ),
    ).toBeDefined();
    expect(figures(container)).toEqual({
      Measures: { value: "4", tone: "info" },
      "Meeting their target": { value: "2", tone: "success" },
      "Below target": { value: "1", tone: "danger" },
      "Not measured yet": { value: "1", tone: "neutral" },
    });
    expect(
      screen.getByRole("table", { name: "Each measure from the evaluation run, with its target" }),
    ).toBeDefined();

    const recall = metricRow(container, "q_recall");
    expect(recall.textContent).toContain("Share of gold clauses present in the retrieved set.");
    expect(recall.textContent).toContain("93.4%");
    expect(recall.textContent).toContain("At least 92%");
    expect(recall.querySelector("[data-slot='status-chip']")?.textContent).toBe("Meets target");
    const grounded = metricRow(container, "q_grounded");
    expect(grounded.textContent).toContain("95.1%");
    expect(grounded.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(metricRow(container, "q_citation").textContent).toContain("Meets target");
    const refusal = metricRow(container, "q_refusal");
    expect(refusal.textContent).toContain("At least 95%");
    expect(refusal.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "neutral",
    );
    expect(refusal.textContent?.match(/Not measured yet/g)).toHaveLength(2);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("describes the latest run without a date and keeps no shortfall neutral", () => {
    const { container } = render(
      <SystemQualityView
        metrics={METRICS.filter((item) => item.id !== "q_grounded")}
        measuredAt={null}
      />,
    );
    expect(
      screen.getByText(
        "How our answers and rules measure up against the targets we hold ourselves to, from the latest evaluation run.",
      ),
    ).toBeDefined();
    expect(figures(container)["Below target"]).toEqual({ value: "0", tone: "neutral" });
  });

  it("explains the page before the first evaluation run", async () => {
    const { container } = render(<SystemQualityView metrics={[]} measuredAt={null} />);
    expect(screen.getByRole("heading", { level: 2, name: "No quality numbers yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
