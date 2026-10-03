import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ReportRow } from "./report-filters";
import { ReportsTable } from "./reports-table";

function row(overrides: Partial<ReportRow>): ReportRow {
  return {
    id: "r1",
    title: "Wrong due date for GSTR-3B",
    message: "The obligation says the 20th but the notification moved it to the 22nd.",
    subject: "GSTR-3B monthly return",
    href: "/admin/error-reports/r1",
    severity: "critical",
    severityLabel: "Critical",
    severityTone: "danger",
    status: "open",
    statusLabel: "Open",
    statusTone: "warning",
    reportedLabel: "1 Oct 2026, 10:30 am IST",
    ...overrides,
  };
}

const ROWS = [
  row({}),
  row({
    id: "r2",
    title: "TDS rate is out of date",
    message: "The rate changed in the last budget.",
    subject: "TDS on rent",
    href: null,
    severity: "low",
    severityLabel: "Low",
    severityTone: "info",
    status: "dismissed",
    statusLabel: "Dismissed",
    statusTone: "neutral",
  }),
];

const OPTIONS = {
  severityOptions: [
    { value: "critical", label: "Critical" },
    { value: "low", label: "Low" },
  ],
  statusOptions: [
    { value: "open", label: "Open" },
    { value: "dismissed", label: "Dismissed" },
  ],
};

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-report]")].map(
    (node) => node.getAttribute("data-report") ?? "",
  );
}

describe("ReportsTable", () => {
  it("shows every report with its message, subject, severity, status and date", async () => {
    const { container } = render(<ReportsTable rows={ROWS} {...OPTIONS} />);
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 2 reports.");
    expect(screen.getByRole("table", { name: "Reported errors" })).toBeDefined();

    const first = container.querySelector("[data-report='r1']") as HTMLElement;
    expect(within(first).getByRole("link", { name: "Wrong due date for GSTR-3B" })).toHaveProperty(
      "href",
      expect.stringContaining("/admin/error-reports/r1"),
    );
    expect(first.textContent).toContain("moved it to the 22nd");
    expect(first.textContent).toContain("GSTR-3B monthly return");
    const badge = first.querySelector("[data-slot='badge']");
    expect(badge?.textContent).toBe("Critical");
    expect(badge?.getAttribute("data-tone")).toBe("danger");
    expect(first.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "warning",
    );
    expect(first.textContent).toContain("1 Oct 2026, 10:30 am IST");

    const second = container.querySelector("[data-report='r2']") as HTMLElement;
    expect(within(second).queryByRole("link")).toBeNull();
    expect(within(second).getByText("TDS rate is out of date")).toBeDefined();
    expect(second.querySelector("[data-slot='status-chip']")?.textContent).toBe("Dismissed");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by search, severity and status, and says when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<ReportsTable rows={ROWS} {...OPTIONS} />);

    await user.type(screen.getByLabelText("Search by title or subject"), "monthly");
    expect(shownIds(container)).toEqual(["r1"]);
    await user.clear(screen.getByLabelText("Search by title or subject"));

    await user.selectOptions(screen.getByLabelText("Severity"), "low");
    expect(shownIds(container)).toEqual(["r2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 2 reports.");

    await user.selectOptions(screen.getByLabelText("Status"), "open");
    expect(shownIds(container)).toEqual([]);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No reports match" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.selectOptions(screen.getByLabelText("Severity"), "all");
    expect(shownIds(container)).toEqual(["r1"]);
  });
});
