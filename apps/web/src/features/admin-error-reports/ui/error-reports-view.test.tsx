import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { ErrorReport } from "../model/error-reports";
import { AdminErrorReportsView } from "./error-reports-view";

const hrefFor = (id: string) => `/admin/error-reports/${id}` as Route;

const REPORTS: ErrorReport[] = [
  {
    id: "err_resolved",
    title: "Missing late fee",
    message: "The late fee for GSTR-1 is not shown.",
    subject: "GSTR-1",
    severity: "critical",
    status: "resolved",
    reportedAt: "2026-09-20T05:00:00Z",
  },
  {
    id: "err_low",
    title: "TDS rate is out of date",
    message: "The rate changed in the last budget.",
    subject: "TDS on rent",
    severity: "low",
    status: "open",
    reportedAt: "2026-09-25T05:00:00Z",
  },
  {
    id: "err_high",
    title: "Wrong due date for GSTR-3B",
    message: "The notification moved it to the 22nd.",
    subject: "GSTR-3B monthly return",
    severity: "high",
    status: "open",
    reportedAt: "2026-10-01T05:00:00Z",
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

describe("AdminErrorReportsView", () => {
  it("counts the reports and lists them open and most serious first, worded and linked", async () => {
    const { container } = render(<AdminErrorReportsView reports={REPORTS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Error reports" })).toBeDefined();
    expect(figures(container)).toEqual({
      Reports: { value: "3", tone: "info" },
      Open: { value: "2", tone: "warning" },
      "Open, critical or high": { value: "1", tone: "danger" },
      Resolved: { value: "1", tone: "success" },
    });

    const rows = [...container.querySelectorAll<HTMLElement>("[data-report]")];
    expect(rows.map((row) => row.getAttribute("data-report"))).toEqual([
      "err_high",
      "err_low",
      "err_resolved",
    ]);
    expect(rows[0]?.textContent).toContain("GSTR-3B monthly return");
    expect(rows[0]?.textContent).toContain(formatDateTime("2026-10-01T05:00:00Z"));
    expect(rows[1]?.querySelector("[data-slot='badge']")?.textContent).toBe("Low");
    expect(rows[2]?.querySelector("[data-slot='status-chip']")?.textContent).toBe("Resolved");
    expect(screen.getByRole("link", { name: "Missing late fee" }).getAttribute("href")).toBe(
      "/admin/error-reports/err_resolved",
    );
    expect(screen.getAllByRole("option", { name: "Dismissed" })).toHaveLength(1);
    expect(screen.getAllByRole("option", { name: "Critical" })).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the titles unlinked without a report page and the figures neutral when nothing is open", () => {
    const resolved = REPORTS.filter((report) => report.status === "resolved");
    const { container } = render(<AdminErrorReportsView reports={resolved} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Missing late fee")).toBeDefined();
    expect(figures(container).Open).toEqual({ value: "0", tone: "neutral" });
    expect(figures(container)["Open, critical or high"]).toEqual({ value: "0", tone: "neutral" });
  });

  it("shows the empty state before anyone reports an error", async () => {
    const { container } = render(<AdminErrorReportsView reports={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 2, name: "No error reports" })).toBeDefined();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(container.querySelector("[data-slot='reports-table']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
