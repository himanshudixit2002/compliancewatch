import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { queuedTaskFromDto, reviewStatsFromDto } from "@/entities/rule-version/mappers";
import { breadcrumbsFor } from "@/shared/config/nav";
import type { WriteAction } from "@/shared/ui/write-outcome";
import { EXAMPLE_ANALYST_ID } from "@/test/rule-version-fixture";
import {
  EXAMPLE_CANDIDATE_TASK_ID,
  EXAMPLE_TASK_ID,
  queuedCandidateTaskDto,
  queuedTaskDto,
  reviewStatsDto,
} from "@/test/review-task-fixture";
import { queueView, type QueueFilter } from "../model/queue";
import { statsStrip } from "../model/stats";
import type { WriteResult } from "./form-shared";
import { QueueView, type QueueViewProps } from "./queue-view";

const OPEN: QueueFilter = { status: "open", kind: null, regulator: null, cursor: null };

function props(overrides: Partial<QueueViewProps> = {}): QueueViewProps {
  return {
    title: "Review queue",
    crumbs: breadcrumbsFor("admin.review"),
    filter: OPEN,
    view: queueView(
      OPEN,
      [
        queuedTaskFromDto(
          queuedTaskDto({
            status: "claimed",
            claimed_by: EXAMPLE_ANALYST_ID,
            claimed_at: "2000-05-01T05:00:00Z",
          }),
        ),
        queuedTaskFromDto(queuedCandidateTaskDto()),
      ],
      "next",
      EXAMPLE_ANALYST_ID,
    ),
    strip: statsStrip(reviewStatsFromDto(reviewStatsDto())),
    regulators: ["example_regulator"],
    access: { allowed: true },
    claim: vi.fn<WriteAction<WriteResult>>(),
    openSeedTasks: vi.fn<WriteAction<WriteResult>>(),
    sampling: null,
    ...overrides,
  };
}

describe("QueueView", () => {
  it("shows the strip, the filters and each task with its version, candidate and claim", async () => {
    const { container } = render(<QueueView {...props()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Review queue" })).toBeDefined();
    expect(container.querySelector("[data-slot='review-strip-cards']")?.textContent).toContain(
      "Open3",
    );
    expect(screen.getByRole("link", { name: "Review stats" }).getAttribute("href")).toBe(
      "/admin/review/stats",
    );
    expect(screen.getByRole("navigation", { name: "Show tasks by status" })).toBeDefined();
    expect(screen.getByRole("link", { name: "example_regulator" }).getAttribute("href")).toBe(
      "/admin/review?regulator=example_regulator",
    );
    const mine = container.querySelector(`tr[data-task='${EXAMPLE_TASK_ID}']`);
    expect(mine?.getAttribute("data-mine")).toBe("true");
    expect(mine?.textContent).toContain("Yours");
    expect(mine?.textContent).toContain("Claimed by you");
    expect(mine?.querySelector("button")).toBeNull();
    const candidate = container.querySelector(`tr[data-task='${EXAMPLE_CANDIDATE_TASK_ID}']`);
    expect(candidate?.textContent).toContain("Suggested key: example_suggested_rule");
    expect(candidate?.textContent).toContain("Not drafted yet");
    expect(candidate?.textContent).toContain("Confidence 82%");
    expect(candidate?.textContent).toContain("High impact");
    expect(screen.getByRole("button", { name: "Claim: Example candidate title" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      "/admin/review?cursor=next",
    );
    expect(screen.getByText("Open: 2 tasks on this page")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("claims a row, and opens the seed tasks with the answer said", async () => {
    const claim = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => ({
      status: "ok",
      message: "Example claimed.",
      value: {
        kind: "done",
        message: `Example claimed ${String(formData.get("task_id"))}.`,
        details: [],
        links: [],
      },
    }));
    const openSeedTasks = vi.fn<WriteAction<WriteResult>>(async () => ({
      status: "ok",
      message: "Review tasks opened for seed drafts: 2.",
      value: {
        kind: "done",
        message: "Review tasks opened for seed drafts: 2.",
        details: [],
        links: [],
      },
    }));
    const user = userEvent.setup();
    const { container } = render(<QueueView {...props({ claim, openSeedTasks })} />);
    await user.click(screen.getByRole("button", { name: "Claim: Example candidate title" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='queue-claim-outcome']")?.textContent).toContain(
        `Example claimed ${EXAMPLE_CANDIDATE_TASK_ID}.`,
      ),
    );
    await user.click(screen.getByRole("button", { name: "Open seed tasks" }));
    await waitFor(() =>
      expect(container.querySelector("[data-slot='seed-tasks-outcome']")?.textContent).toContain(
        "Review tasks opened for seed drafts: 2.",
      ),
    );
  });

  it("moves with j and k over a roving tab stop, claims with c, and lists the keys with ?", async () => {
    const claim = vi.fn<WriteAction<WriteResult>>(async () => ({ status: "idle" }));
    const user = userEvent.setup();
    render(<QueueView {...props({ claim })} />);
    const links = screen.getAllByRole("link", { name: /Example (rule|candidate) title/ });
    expect(links.map((link) => link.getAttribute("tabindex"))).toEqual(["0", "-1"]);
    await user.keyboard("j");
    expect(document.activeElement).toBe(links[0]);
    await user.keyboard("j");
    expect(document.activeElement).toBe(links[1]);
    expect(links.map((link) => link.getAttribute("tabindex"))).toEqual(["-1", "0"]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(links[0]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(links[1]);
    await user.keyboard("c");
    await waitFor(() => expect(claim).toHaveBeenCalledTimes(1));
    // The claim's answer takes the focus; k brings it back to the current row, then moves on.
    await waitFor(() =>
      expect(document.activeElement?.getAttribute("data-slot")).toBe("queue-claim-outcome"),
    );
    await user.keyboard("k");
    expect(document.activeElement).toBe(links[1]);
    await user.keyboard("k");
    expect(document.activeElement).toBe(links[0]);
    await user.keyboard("c");
    expect(claim).toHaveBeenCalledTimes(1);
    await user.keyboard("?");
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeDefined();
    await user.keyboard("j");
    expect(document.activeElement).not.toBe(links[1]);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("leaves a key typed into a field or with a modifier alone", () => {
    const claim = vi.fn<WriteAction<WriteResult>>();
    render(
      <>
        <input aria-label="Example field" />
        <QueueView {...props({ claim })} />
      </>,
    );
    const field = screen.getByLabelText("Example field");
    field.focus();
    fireEvent.keyDown(field, { key: "j" });
    expect(document.activeElement).toBe(field);
    fireEvent.keyDown(document.body, { key: "j", ctrlKey: true });
    expect(document.activeElement).toBe(field);
  });

  it("says why a page is empty, why the access is refused, and shows a failed read", async () => {
    const { container, rerender } = render(
      <QueueView
        {...props({
          filter: { ...OPEN, kind: "candidate" },
          view: queueView({ ...OPEN, kind: "candidate" }, [], null, EXAMPLE_ANALYST_ID),
          access: { allowed: false, title: "The web.admin_rulebook_writes flag is off" },
          claim: null,
          openSeedTasks: null,
          strip: null,
          stripError: { message: "Example stats failure", requestId: "example-id" },
          sampling: {
            title: "Review sampling",
            waitingFor: "POST /v1/rulebook/review/samples (not scheduled)",
          },
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "No task matches these filters" })).toBeDefined();
    expect(screen.getByText("The web.admin_rulebook_writes flag is off")).toBeDefined();
    expect(screen.getByText("Example stats failure")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Open seed tasks" })).toBeNull();
    expect(container.querySelector("[data-slot='review-sampling']")?.textContent).toBe(
      "Review sampling is not built yet: it waits for POST /v1/rulebook/review/samples (not scheduled).",
    );
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <QueueView
        {...props({
          view: null,
          error: { message: "Example queue failure", requestId: "example-id" },
        })}
      />,
    );
    expect(screen.getByText("Example queue failure")).toBeDefined();
  });
});
