import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { BackfillJob } from "../model/backfill";
import { AdminBackfillView, type StartBackfillAction } from "./backfill-view";

const JOBS: BackfillJob[] = [
  {
    id: "bf_decisions",
    name: "Applicability decisions",
    service: "applicability-engine",
    status: "running",
    processed: 4200,
    total: 10000,
    startedAt: "2026-10-02T04:00:00Z",
    finishedAt: null,
  },
  {
    id: "bf_counting",
    name: "Notification work index",
    service: "notification",
    status: "running",
    processed: 35,
    total: null,
    startedAt: "2026-10-02T04:30:00Z",
    finishedAt: null,
  },
  {
    id: "bf_queued",
    name: "Obligation due dates",
    service: "obligation",
    status: "pending",
    processed: 0,
    total: null,
    startedAt: null,
    finishedAt: null,
  },
  {
    id: "bf_profiles",
    name: "Profile versions",
    service: "profile",
    status: "failed",
    processed: 120,
    total: 500,
    startedAt: "2026-10-01T09:00:00Z",
    finishedAt: "2026-10-01T09:20:00Z",
  },
  {
    id: "bf_clauses",
    name: "Clause embeddings",
    service: "rulebook",
    status: "completed",
    processed: 800,
    total: 800,
    startedAt: "2026-09-30T10:00:00Z",
    finishedAt: "2026-09-30T11:00:00Z",
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
  return [...container.querySelectorAll("[data-job]")].map(
    (item) => item.getAttribute("data-job") ?? "",
  );
}

function jobRow(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-job='${id}']`) as HTMLElement;
}

describe("AdminBackfillView", () => {
  it("offers the start form and shows each job's progress as the job reports it", async () => {
    const startAction = vi.fn<StartBackfillAction>(async () => undefined);
    const { container } = render(<AdminBackfillView jobs={JOBS} startAction={startAction} />);
    expect(screen.getByRole("heading", { level: 1, name: "Backfill" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Start a backfill" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Start backfill" })).toBeDefined();
    expect(figures(container)).toEqual({
      Jobs: { value: "5", tone: "info" },
      Running: { value: "2", tone: "neutral" },
      Completed: { value: "1", tone: "success" },
      Failed: { value: "1", tone: "danger" },
    });
    expect(shownIds(container)).toEqual([
      "bf_decisions",
      "bf_counting",
      "bf_queued",
      "bf_profiles",
      "bf_clauses",
    ]);

    const bar = screen.getByRole("progressbar", { name: "Progress of Applicability decisions" });
    expect(bar.getAttribute("aria-valuenow")).toBe("4200");
    expect(bar.getAttribute("aria-valuemax")).toBe("10000");
    expect(bar.getAttribute("aria-valuetext")).toBe("4200 of 10000 records");
    const decisions = jobRow(container, "bf_decisions");
    expect(decisions.textContent).toContain("Service: applicability-engine");
    expect(decisions.textContent).toContain(formatDateTime("2026-10-02T04:00:00Z"));
    expect(decisions.textContent).toContain("Not finished");
    expect(decisions.querySelector("[data-slot='status-chip']")?.textContent).toBe("Running");

    const counting = jobRow(container, "bf_counting");
    expect(within(counting).queryByRole("progressbar")).toBeNull();
    expect(counting.textContent).toContain("35 records so far");
    const queued = jobRow(container, "bf_queued");
    expect(within(queued).queryByRole("progressbar")).toBeNull();
    expect(queued.textContent).toContain("Waiting to start");
    expect(queued.textContent).toContain("Not started");

    const failed = jobRow(container, "bf_profiles");
    expect(within(failed).getByRole("progressbar").getAttribute("aria-valuetext")).toBe(
      "120 of 500 records",
    );
    expect(failed.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(jobRow(container, "bf_clauses").textContent).toContain(
      formatDateTime("2026-09-30T11:00:00Z"),
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("submits the start form to the action", async () => {
    const user = userEvent.setup();
    const startAction = vi.fn<StartBackfillAction>(async () => undefined);
    render(<AdminBackfillView jobs={JOBS} startAction={startAction} />);
    await user.click(screen.getByRole("button", { name: "Start backfill" }));
    await waitFor(() => expect(startAction).toHaveBeenCalledTimes(1));
    expect(startAction.mock.calls[0]?.[0]).toBeInstanceOf(FormData);
  });

  it("leaves out the start form without an action and keeps no failures neutral", () => {
    const { container } = render(
      <AdminBackfillView jobs={JOBS.filter((job) => job.status !== "failed")} />,
    );
    expect(container.querySelector("[data-slot='start-backfill']")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(figures(container).Failed).toEqual({ value: "0", tone: "neutral" });
  });

  it("explains an empty list, under the start form when there is one", async () => {
    const startAction = vi.fn<StartBackfillAction>(async () => undefined);
    const { container, unmount } = render(
      <AdminBackfillView jobs={[]} startAction={startAction} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No backfills yet" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Start backfill" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();

    render(<AdminBackfillView jobs={[]} />);
    expect(screen.getByRole("heading", { level: 2, name: "No backfills yet" })).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
