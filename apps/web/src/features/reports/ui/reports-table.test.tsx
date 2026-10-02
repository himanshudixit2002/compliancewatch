import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ReportRow } from "./report-filters";
import { ReportsTable } from "./reports-table";

function row(overrides: Partial<ReportRow>): ReportRow {
  return {
    id: "1",
    name: "Quarterly compliance",
    format: "pdf",
    formatLabel: "PDF",
    status: "ready",
    statusLabel: "Ready",
    statusTone: "success",
    generatedAt: "10 Apr 2026, 5:30 pm IST",
    size: "1.2 MB",
    downloadUrl: "https://files.example.com/1.pdf",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    name: "GST summary",
    format: "xlsx",
    formatLabel: "Excel",
    status: "generating",
    statusLabel: "Generating",
    statusTone: "warning",
    downloadUrl: null,
  }),
];

const OPTIONS = {
  formatOptions: [
    { value: "pdf", label: "PDF" },
    { value: "xlsx", label: "Excel" },
  ],
  statusOptions: [
    { value: "ready", label: "Ready" },
    { value: "generating", label: "Generating" },
  ],
};

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-report]")].map(
    (item) => item.getAttribute("data-report") ?? "",
  );
}

describe("ReportsTable", () => {
  it("lists the reports with a download link only for a ready file", async () => {
    const { container } = render(<ReportsTable rows={ROWS} {...OPTIONS} />);
    expect(screen.getByRole("table", { name: "Compliance reports" })).toBeDefined();
    const ready = container.querySelector("[data-report='1']") as HTMLElement;
    const link = within(ready).getByRole("link", { name: /^Download\s*Quarterly compliance$/ });
    expect(link.getAttribute("href")).toBe("https://files.example.com/1.pdf");
    expect(link.hasAttribute("download")).toBe(true);
    const generating = container.querySelector("[data-report='2']") as HTMLElement;
    expect(within(generating).queryByRole("link")).toBeNull();
    expect(within(generating).getByText("Not available")).toBeDefined();
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 2 reports.");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by name, format and status, and says when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<ReportsTable rows={ROWS} {...OPTIONS} />);

    await user.type(screen.getByLabelText("Search by name"), "gst");
    expect(shownIds(container)).toEqual(["2"]);
    await user.clear(screen.getByLabelText("Search by name"));

    await user.selectOptions(screen.getByLabelText("Format"), "pdf");
    expect(shownIds(container)).toEqual(["1"]);

    await user.selectOptions(screen.getByLabelText("Status"), "generating");
    expect(shownIds(container)).toEqual([]);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { name: "No reports match" })).toBeDefined();
    expect(screen.getByRole("status").textContent).toBe("Showing 0 of 2 reports.");
  });
});
