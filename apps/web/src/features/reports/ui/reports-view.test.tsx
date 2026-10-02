import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ReportItem } from "../model/reports";
import { ReportsView } from "./reports-view";

const REPORTS: ReportItem[] = [
  {
    id: "rep_1",
    name: "Quarterly compliance",
    format: "pdf",
    status: "ready",
    generatedAt: "2026-04-10T12:00:00Z",
    size: "1.2 MB",
    url: "https://files.example.com/rep_1.pdf",
  },
  {
    id: "rep_2",
    name: "GST summary",
    format: "csv",
    status: "failed",
    generatedAt: "2026-04-11T12:00:00Z",
    size: "0 KB",
    url: null,
  },
];

function figure(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("ReportsView", () => {
  it("summarises the reports and lists them, worded, with the generate link", async () => {
    const { container } = render(<ReportsView reports={REPORTS} generateHref="/reports/new" />);
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeDefined();
    expect(figure(container, "Total reports")).toBe("2");
    expect(figure(container, "Ready")).toBe("1");
    expect(figure(container, "Generating")).toBe("0");
    expect(screen.getByRole("link", { name: "Generate report" }).getAttribute("href")).toBe(
      "/reports/new",
    );
    const failed = container.querySelector("[data-report='rep_2']") as HTMLElement;
    expect(failed.textContent).toContain("CSV");
    expect(failed.textContent).toContain("Failed");
    expect(failed.textContent).toContain("11 Apr 2026, 5:30 pm IST");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the empty state, with the generate link in it when generating is offered", async () => {
    const { container } = render(<ReportsView reports={[]} generateHref="/reports/new" />);
    expect(screen.getByRole("heading", { name: "No reports yet" })).toBeDefined();
    expect(screen.getAllByRole("link", { name: "Generate report" })).toHaveLength(2);
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers no generate link while generating is not available", () => {
    render(<ReportsView reports={[]} generateHref={null} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
