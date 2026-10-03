import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import { RUN_ID_FIELD, type PipelineRun } from "../model/pipeline";
import { PipelineView, type RetryAction } from "./pipeline-view";

const RUNS: PipelineRun[] = [
  {
    id: "run_fetch",
    name: "Example circulars",
    stage: "fetch",
    status: "running",
    processed: 120,
    total: 300,
    startedAt: "2000-10-02T04:00:00Z",
    finishedAt: null,
    error: null,
  },
  {
    id: "run_parse",
    name: "Example notices",
    stage: "parse",
    status: "failed",
    processed: 40,
    total: 90,
    startedAt: "2000-10-02T03:00:00Z",
    finishedAt: "2000-10-02T03:12:05Z",
    error: "The source answered 503",
  },
  {
    id: "run_extract",
    name: "Example filings",
    stage: "extract",
    status: "completed",
    processed: 75,
    total: 75,
    startedAt: "2000-10-01T10:00:00Z",
    finishedAt: "2000-10-01T12:04:00Z",
    error: null,
  },
  {
    id: "run_queued",
    name: "Example directions",
    stage: "fetch",
    status: "pending",
    processed: 0,
    total: null,
    startedAt: null,
    finishedAt: null,
    error: null,
  },
  {
    id: "run_counting",
    name: "Example bulletins",
    stage: "fetch",
    status: "running",
    processed: 12,
    total: null,
    startedAt: "2000-10-02T04:30:00Z",
    finishedAt: null,
    error: null,
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

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-run]")].map(
    (item) => item.getAttribute("data-run") ?? "",
  );
}

function runRow(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-run='${id}']`) as HTMLElement;
}

describe("PipelineView", () => {
  it("summarises the runs and shows each one's progress, timing and failure", async () => {
    const retryAction = vi.fn<RetryAction>(async () => undefined);
    const { container } = render(<PipelineView runs={RUNS} retryAction={retryAction} />);
    expect(screen.getByRole("heading", { level: 1, name: "Pipeline" })).toBeDefined();
    expect(figures(container)).toEqual({
      Runs: { value: "5", tone: "info" },
      Running: { value: "2", tone: "neutral" },
      Completed: { value: "1", tone: "success" },
      Failed: { value: "1", tone: "danger" },
    });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "All (5)",
      "Running (2)",
      "Failed (1)",
      "Pending (1)",
      "Completed (1)",
    ]);
    expect(shownIds(container)).toEqual([
      "run_fetch",
      "run_parse",
      "run_extract",
      "run_queued",
      "run_counting",
    ]);

    const bar = screen.getByRole("progressbar", { name: "Progress of Example circulars" });
    expect(bar.getAttribute("aria-valuenow")).toBe("120");
    expect(bar.getAttribute("aria-valuemax")).toBe("300");
    expect(bar.getAttribute("aria-valuetext")).toBe("120 of 300 documents");
    const fetch = runRow(container, "run_fetch");
    expect(fetch.textContent).toContain(formatDateTime("2000-10-02T04:00:00Z"));
    expect(fetch.textContent).toContain("Not finished");
    expect(fetch.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "info",
    );

    const parse = runRow(container, "run_parse");
    expect(parse.textContent).toContain("Error: The source answered 503");
    expect(parse.textContent).toContain("12 min 5 s");
    expect(parse.textContent).toContain("40 of 90 documents");
    expect(runRow(container, "run_extract").textContent).toContain("2 h 4 min");

    const queued = runRow(container, "run_queued");
    expect(within(queued).queryByRole("progressbar")).toBeNull();
    expect(queued.textContent).toContain("Waiting to start");
    expect(queued.textContent).toContain("Not started");
    const counting = runRow(container, "run_counting");
    expect(within(counting).queryByRole("progressbar")).toBeNull();
    expect(counting.textContent).toContain("12 documents so far");

    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeDefined();
    expect(screen.getAllByRole("button", { name: /^Retry/ })).toHaveLength(1);
    expect(within(parse).getByRole("button", { name: /^Retry\s*Example notices$/ })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends the failed run's id to the retry action", async () => {
    const user = userEvent.setup();
    const retryAction = vi.fn<RetryAction>(async () => undefined);
    render(<PipelineView runs={RUNS} retryAction={retryAction} />);
    await user.click(screen.getByRole("button", { name: /^Retry\s*Example notices$/ }));
    await waitFor(() => expect(retryAction).toHaveBeenCalledTimes(1));
    const formData = retryAction.mock.calls[0]?.[0] as FormData;
    expect(formData.get(RUN_ID_FIELD)).toBe("run_parse");
  });

  it("shows the runs of one status in its tab", async () => {
    const user = userEvent.setup();
    const { container } = render(<PipelineView runs={RUNS} />);
    await user.click(screen.getByRole("tab", { name: "Failed (1)" }));
    expect(shownIds(container)).toEqual(["run_parse"]);
    await user.click(screen.getByRole("tab", { name: "Running (2)" }));
    expect(shownIds(container)).toEqual(["run_fetch", "run_counting"]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers no retry without an action, and says when a status has no runs", async () => {
    const user = userEvent.setup();
    const healthy = RUNS.filter((item) => item.status !== "failed");
    const { container } = render(<PipelineView runs={healthy} />);
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(figures(container).Failed).toEqual({ value: "0", tone: "neutral" });

    await user.click(screen.getByRole("tab", { name: "Failed (0)" }));
    expect(shownIds(container)).toEqual([]);
    expect(
      screen.getByRole("heading", { level: 2, name: "No runs with this status" }),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("explains an empty pipeline instead of showing the tabs", async () => {
    const { container } = render(<PipelineView runs={[]} />);
    expect(screen.getByRole("heading", { level: 2, name: "No pipeline runs yet" })).toBeDefined();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
