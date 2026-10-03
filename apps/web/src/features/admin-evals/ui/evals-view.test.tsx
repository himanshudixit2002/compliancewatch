import type { Route } from "next";
import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { EvalRun } from "../model/evals";
import { AdminEvalsView } from "./evals-view";

const hrefFor = (id: string) => `/admin/evals/runs/${id}` as Route;

const RUNS: EvalRun[] = [
  {
    id: "run_old",
    name: "Extraction, nightly",
    model: "claude-sonnet-4-5",
    status: "failed",
    score: 0.62,
    startedAt: "2026-09-30T21:00:00Z",
  },
  {
    id: "run_new",
    name: "Questions and answers, CI",
    model: "scripted",
    status: "running",
    score: null,
    startedAt: "2026-10-02T21:00:00Z",
  },
  {
    id: "run_mid",
    name: "Relations, nightly",
    model: "claude-sonnet-4-5",
    status: "passed",
    score: 0.9,
    startedAt: "2026-10-01T21:00:00Z",
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

describe("AdminEvalsView", () => {
  it("summarises the runs and lists them newest first with model, outcome, score and start", async () => {
    const { container } = render(<AdminEvalsView runs={RUNS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Evals" })).toBeDefined();
    expect(figures(container)).toEqual({
      Runs: { value: "3", tone: "info" },
      "Average score": { value: "76%", tone: "neutral" },
      Passed: { value: "1", tone: "success" },
      Failed: { value: "1", tone: "danger" },
    });
    expect(screen.getByText("Runs with a score: 2")).toBeDefined();
    expect(screen.getByRole("table", { name: "Evaluation runs" })).toBeDefined();

    const rows = [...container.querySelectorAll<HTMLElement>("[data-run]")];
    expect(rows.map((row) => row.getAttribute("data-run"))).toEqual([
      "run_new",
      "run_mid",
      "run_old",
    ]);
    const running = rows[0] as HTMLElement;
    expect(within(running).getByRole("link", { name: "Questions and answers, CI" })).toHaveProperty(
      "href",
      expect.stringContaining("/admin/evals/runs/run_new"),
    );
    expect(running.textContent).toContain("scripted");
    expect(running.querySelector("[data-slot='status-chip']")?.textContent).toBe("Running");
    expect(running.textContent).toContain("No score yet");
    expect(running.textContent).toContain(formatDateTime("2026-10-02T21:00:00Z"));
    const failed = rows[2] as HTMLElement;
    expect(failed.textContent).toContain("62%");
    expect(failed.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the names unlinked without a run page and has no average before any score", () => {
    const running = RUNS.filter((entry) => entry.status === "running");
    const { container } = render(<AdminEvalsView runs={running} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Questions and answers, CI").tagName).toBe("SPAN");
    expect(figures(container)["Average score"]?.value).toBe("No score yet");
    expect(screen.getByText("Runs with a score: 0")).toBeDefined();
    expect(figures(container).Failed).toEqual({ value: "0", tone: "neutral" });
  });

  it("shows the empty state before the first run", async () => {
    const { container } = render(<AdminEvalsView runs={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 2, name: "No evaluation runs" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
