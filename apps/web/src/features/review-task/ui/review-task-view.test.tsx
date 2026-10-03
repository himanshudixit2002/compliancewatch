import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import { REVIEW_DECISION_FIELDS, type ReviewTask } from "../model/review-task";
import { ReviewTaskView } from "./review-task-view";

const NOW = new Date("2026-10-15T06:30:00Z");

const BACK = "/admin/review" as Route;

const PENDING: ReviewTask = {
  id: "task_1",
  type: "obligation_review",
  status: "pending",
  priority: "high",
  assignee: null,
  title: "New TDS obligation",
  description: "The pipeline proposed a monthly TDS deposit for this business.",
  createdAt: "2026-10-10T04:00:00Z",
  dueAt: "2026-10-14T12:30:00Z",
  metadata: {
    nodeId: "node_42",
    financialYear: "2026-27",
    reason: "low_confidence",
    documentId: "doc_7",
  },
};

const DECIDED: ReviewTask = {
  ...PENDING,
  status: "approved",
  priority: "low",
  assignee: "Asha Rao",
  dueAt: null,
  metadata: {},
};

type Action = (formData: FormData) => Promise<void>;

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

/** Each detail's label and value; an identifier's value is its code, without the copy button. */
function details(): Record<string, string> {
  const section = screen.getByRole("heading", { level: 2, name: "Details" })
    .parentElement as HTMLElement;
  return Object.fromEntries(
    [...section.querySelectorAll("dt")].map((dt) => {
      const value = dt.nextElementSibling;
      return [dt.textContent ?? "", (value?.querySelector("code") ?? value)?.textContent ?? ""];
    }),
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ReviewTaskView", () => {
  it("shows a pending task past its due time with its metadata, decision forms and claim", async () => {
    const decideAction = vi.fn<Action>(async () => undefined);
    const claimAction = vi.fn<Action>(async () => undefined);
    const { container } = render(
      <ReviewTaskView
        task={PENDING}
        backHref={BACK}
        decideAction={decideAction}
        claimAction={claimAction}
        now={NOW}
      />,
    );
    expect(screen.getByRole("link", { name: "Back to review queue" }).getAttribute("href")).toBe(
      "/admin/review",
    );
    expect(screen.getByRole("heading", { level: 1, name: "New TDS obligation" })).toBeDefined();
    expect(
      screen.getByText("The pipeline proposed a monthly TDS deposit for this business."),
    ).toBeDefined();
    expect(figures(container)).toEqual({
      Status: { value: "Pending", tone: "warning" },
      Priority: { value: "High", tone: "danger" },
      Assignee: { value: "Unassigned", tone: "neutral" },
      Due: { value: "14 Oct 2026, 6:00 pm IST", tone: "danger" },
    });
    expect(screen.getByText("Past its due time")).toBeDefined();
    expect(details()).toEqual({
      ID: "task_1",
      Type: "Obligation review",
      Created: "10 Oct 2026, 9:30 am IST",
      Node: "node_42",
      "Financial year": "2026-27",
      "Why it was opened": "Low confidence",
      "Source document": "doc_7",
    });
    expect(screen.getByRole("button", { name: "Copy ID" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Copy Source document" })).toBeDefined();

    const decision = screen.getByRole("heading", { level: 2, name: "Decision" })
      .parentElement as HTMLElement;
    const reason = within(decision).getByLabelText(/^Reason for rejecting/) as HTMLTextAreaElement;
    expect(reason.name).toBe(REVIEW_DECISION_FIELDS.reason);
    expect(reason.required).toBe(true);
    expect(reason.minLength).toBe(10);
    expect(
      within(decision).getByText("At least 10 characters. It is recorded with the decision."),
    ).toBeDefined();
    expect(
      within(decision).getByRole("button", { name: "Reject" }).getAttribute("data-variant"),
    ).toBe("danger");
    expect(await runAxe(container)).toHaveNoViolations();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(decideAction).toHaveBeenCalledTimes(1));
    expect(decideAction.mock.calls[0]?.[0].get(REVIEW_DECISION_FIELDS.decision)).toBe("approve");

    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(decideAction).toHaveBeenCalledTimes(1);
    await user.type(reason, "The rule does not apply to this turnover band.");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(decideAction).toHaveBeenCalledTimes(2));
    const rejected = decideAction.mock.calls[1]?.[0];
    expect(rejected?.get(REVIEW_DECISION_FIELDS.decision)).toBe("reject");
    expect(rejected?.get(REVIEW_DECISION_FIELDS.reason)).toBe(
      "The rule does not apply to this turnover band.",
    );

    await user.click(screen.getByRole("button", { name: "Assign to me" }));
    await waitFor(() => expect(claimAction).toHaveBeenCalledTimes(1));
  });

  it("offers nothing to decide or claim on a decided task, and leaves out absent metadata", async () => {
    const { container } = render(
      <ReviewTaskView
        task={DECIDED}
        backHref={BACK}
        decideAction={vi.fn<Action>(async () => undefined)}
        claimAction={vi.fn<Action>(async () => undefined)}
        now={NOW}
      />,
    );
    expect(figures(container)).toEqual({
      Status: { value: "Approved", tone: "success" },
      Priority: { value: "Low", tone: "neutral" },
      Assignee: { value: "Asha Rao", tone: "info" },
      Due: { value: "No due date", tone: "neutral" },
    });
    expect(screen.queryByText("Past its due time")).toBeNull();
    expect(Object.keys(details())).toEqual(["ID", "Type", "Created"]);
    expect(screen.queryByRole("heading", { name: "Decision" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Assign to me" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("does not offer to claim an assigned task, nor to decide without a decide action", () => {
    render(
      <ReviewTaskView
        task={{ ...PENDING, assignee: "Ravi Kumar" }}
        backHref={BACK}
        claimAction={vi.fn<Action>(async () => undefined)}
        now={NOW}
      />,
    );
    expect(screen.queryByRole("button", { name: "Assign to me" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Decision" })).toBeNull();
    expect(screen.getByText("Ravi Kumar")).toBeDefined();
  });

  it("offers the decision without a claim action, judging the due time against now by default", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const { container } = render(
      <ReviewTaskView
        task={{ ...PENDING, dueAt: "2026-10-16T12:30:00Z" }}
        backHref={BACK}
        decideAction={vi.fn<Action>(async () => undefined)}
      />,
    );
    expect(figures(container).Due).toEqual({ value: "16 Oct 2026, 6:00 pm IST", tone: "neutral" });
    expect(screen.queryByText("Past its due time")).toBeNull();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Assign to me" })).toBeNull();
  });
});
