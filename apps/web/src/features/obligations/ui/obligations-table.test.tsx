import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ObligationRow } from "./obligation-rows";
import { ObligationsTable } from "./obligations-table";

function row(overrides: Partial<ObligationRow>): ObligationRow {
  return {
    id: "1",
    title: "File GSTR-3B for the month",
    href: "/b/biz_1/obligations/1",
    period: "Period 2026-09: 1 Sept 2026 to 30 Sept 2026",
    status: "open",
    statusLabel: "Open",
    statusTone: "info",
    due: "20 Oct 2026",
    dueNote: "Due in 5 days",
    overdue: false,
    evidence: "Filing acknowledgement",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    title: "Pay TDS",
    href: "/b/biz_1/obligations/2",
    period: null,
    status: "in_progress",
    statusLabel: "In progress",
    statusTone: "warning",
    due: "7 Oct 2026",
    dueNote: "Overdue by 8 days",
    overdue: true,
  }),
  row({
    id: "3",
    title: "File GSTR-1",
    period: "Period 2026-08",
    status: "done",
    statusLabel: "Done",
    statusTone: "success",
    due: "11 Sept 2026",
    dueNote: null,
  }),
];

const OPTIONS = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "done", label: "Done" },
  { value: "waived", label: "Waived" },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-obligation]")].map(
    (item) => item.getAttribute("data-obligation") ?? "",
  );
}

describe("ObligationsTable", () => {
  it("lists every obligation with its status, due date and evidence, linked to its page", async () => {
    const { container } = render(<ObligationsTable rows={ROWS} statusOptions={OPTIONS} />);
    expect(shownIds(container)).toEqual(["1", "2", "3"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 3 of 3 obligations.");
    expect(screen.getByRole("table", { name: "The business's obligations" })).toBeDefined();
    const first = container.querySelector("[data-obligation='1']") as HTMLElement;
    expect(within(first).getByRole("link", { name: "File GSTR-3B for the month" })).toHaveProperty(
      "href",
      expect.stringContaining("/b/biz_1/obligations/1"),
    );
    expect(first.textContent).toContain("Period 2026-09: 1 Sept 2026 to 30 Sept 2026");
    expect(first.querySelector("[data-slot='status-chip']")?.textContent).toBe("Open");
    expect(first.textContent).toContain("20 Oct 2026");
    expect(first.querySelector("[data-slot='due-note']")?.className).toContain("text-fg-muted");
    expect(first.textContent).toContain("Filing acknowledgement");
    const overdue = container.querySelector("[data-obligation='2']") as HTMLElement;
    expect(overdue.querySelector("[data-slot='due-note']")?.textContent).toBe("Overdue by 8 days");
    expect(overdue.querySelector("[data-slot='due-note']")?.className).toContain("text-danger");
    expect(overdue.querySelector("p")).toBeNull();
    const done = container.querySelector("[data-obligation='3']") as HTMLElement;
    expect(done.querySelector("[data-slot='due-note']")).toBeNull();
    expect(
      [...(screen.getByLabelText("Status") as HTMLSelectElement).options].map((o) => o.text),
    ).toEqual(["All statuses", "Overdue", "Open", "In progress", "Done", "Waived"]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by status, to the overdue ones and by search, saying when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<ObligationsTable rows={ROWS} statusOptions={OPTIONS} />);

    await user.selectOptions(screen.getByLabelText("Status"), "overdue");
    expect(shownIds(container)).toEqual(["2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 3 obligations.");

    await user.selectOptions(screen.getByLabelText("Status"), "all");
    await user.type(screen.getByLabelText("Search by title or period"), "gstr");
    expect(shownIds(container)).toEqual(["1", "3"]);

    await user.selectOptions(screen.getByLabelText("Status"), "done");
    expect(shownIds(container)).toEqual(["3"]);

    await user.selectOptions(screen.getByLabelText("Status"), "waived");
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { level: 2, name: "No obligations match" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
