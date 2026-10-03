import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { TriageRow } from "./triage-filters";
import { TriageTable } from "./triage-table";

function row(overrides: Partial<TriageRow>): TriageRow {
  return {
    id: "t1",
    question: "When is example return 1 due for March?",
    category: "Example returns",
    href: "/admin/qa-triage/t1",
    reason: "not_covered",
    reasonLabel: "Not covered",
    priorityLabel: "High",
    priorityTone: "danger",
    status: "open",
    statusLabel: "Open",
    statusTone: "warning",
    assignee: "Unassigned",
    createdLabel: "1 Oct 2000, 10:30 am IST",
    ...overrides,
  };
}

const ROWS = [
  row({}),
  row({
    id: "t2",
    question: "Is example tax due on rent?",
    category: "Example tax",
    href: null,
    reason: "thumbs_down",
    reasonLabel: "Marked unhelpful",
    priorityLabel: "Low",
    priorityTone: "neutral",
    status: "closed",
    statusLabel: "Closed",
    statusTone: "success",
    assignee: "Example reviewer",
  }),
];

const OPTIONS = {
  statusOptions: [
    { value: "open", label: "Open" },
    { value: "closed", label: "Closed" },
  ],
  reasonOptions: [
    { value: "not_covered", label: "Not covered" },
    { value: "thumbs_down", label: "Marked unhelpful" },
  ],
};

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-triage]")].map(
    (node) => node.getAttribute("data-triage") ?? "",
  );
}

describe("TriageTable", () => {
  it("shows every question with its topic, reason, priority, status, assignee and date", async () => {
    const { container } = render(<TriageTable rows={ROWS} {...OPTIONS} />);
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 2 questions.");
    expect(screen.getByRole("table", { name: "Questions in the triage queue" })).toBeDefined();

    const first = container.querySelector("[data-triage='t1']") as HTMLElement;
    expect(
      within(first).getByRole("link", { name: "When is example return 1 due for March?" }),
    ).toHaveProperty("href", expect.stringContaining("/admin/qa-triage/t1"));
    expect(first.textContent).toContain("Example returns");
    expect(first.textContent).toContain("Not covered");
    expect(first.querySelector("[data-slot='badge']")?.getAttribute("data-tone")).toBe("danger");
    const chip = first.querySelector("[data-slot='status-chip']");
    expect(chip?.textContent).toBe("Open");
    expect(chip?.getAttribute("data-tone")).toBe("warning");
    expect(first.textContent).toContain("Unassigned");
    expect(first.textContent).toContain("1 Oct 2000, 10:30 am IST");

    const second = container.querySelector("[data-triage='t2']") as HTMLElement;
    expect(within(second).queryByRole("link")).toBeNull();
    expect(within(second).getByText("Is example tax due on rent?")).toBeDefined();
    expect(second.textContent).toContain("Marked unhelpful");
    expect(second.textContent).toContain("Example reviewer");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by search, status and reason, and says when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<TriageTable rows={ROWS} {...OPTIONS} />);

    await user.type(screen.getByLabelText("Search by question or topic"), "tax");
    expect(shownIds(container)).toEqual(["t2"]);
    await user.clear(screen.getByLabelText("Search by question or topic"));

    await user.selectOptions(screen.getByLabelText("Status"), "open");
    expect(shownIds(container)).toEqual(["t1"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 2 questions.");

    await user.selectOptions(screen.getByLabelText("Reason"), "thumbs_down");
    expect(shownIds(container)).toEqual([]);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No questions match" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.selectOptions(screen.getByLabelText("Status"), "all");
    expect(shownIds(container)).toEqual(["t2"]);
  });
});
