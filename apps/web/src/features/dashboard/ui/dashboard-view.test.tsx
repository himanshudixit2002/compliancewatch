import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { emptyDashboard, type DashboardSummary } from "../model/dashboard";
import { DashboardView } from "./dashboard-view";

const NOW = new Date("2026-10-02T06:00:00Z");
const businessHref = (id: string) => `/b/${id}` as Route;
const obligationHref = (businessId: string, obligationId: string) =>
  `/b/${businessId}/obligations/${obligationId}` as Route;

const populated: DashboardSummary = {
  overdue: 1,
  dueThisWeek: 1,
  completed: 2,
  businesses: [
    { id: "b1", name: "Acme Traders", openObligations: 3, overdueObligations: 1 },
    { id: "b2", name: "Bright Foods", openObligations: 1, overdueObligations: 0 },
  ],
  activities: [{ id: "a1", description: "GSTR-1 marked filed", at: "2026-10-01T09:00:00Z" }],
  urgentActions: [
    { businessId: "b1", obligationId: "o1", title: "GSTR-3B", dueDate: "2026-09-30" },
    { businessId: "b2", obligationId: "o2", title: "TDS return", dueDate: "2026-10-05" },
  ],
};

describe("DashboardView", () => {
  it("shows empty states and no businesses section when there is nothing yet", async () => {
    const { container } = render(
      <DashboardView
        view={emptyDashboard()}
        businessHref={businessHref}
        obligationHref={obligationHref}
        now={NOW}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Compliance dashboard" })).toBeDefined();
    expect(screen.getByText("Nothing urgent")).toBeDefined();
    expect(screen.getByText("No recent activity")).toBeDefined();
    expect(screen.queryByRole("heading", { name: "Your businesses" })).toBeNull();
    expect(screen.getByText("None")).toBeDefined();
    expect(container.querySelector("[data-slot='stat-card'][data-tone='danger']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists urgent actions, activity and businesses with their links and tones", async () => {
    const { container } = render(
      <DashboardView
        view={populated}
        businessHref={businessHref}
        obligationHref={obligationHref}
        now={NOW}
      />,
    );
    expect(screen.getByText("50%")).toBeDefined();
    expect(screen.getByRole("link", { name: "GSTR-3B" }).getAttribute("href")).toBe(
      "/b/b1/obligations/o1",
    );
    expect(screen.getByText(/overdue by 2 days/).closest("[data-tone]")).toHaveProperty(
      "dataset.tone",
      "danger",
    );
    expect(screen.getByText(/in 3 days/).closest("[data-tone]")).toHaveProperty(
      "dataset.tone",
      "warning",
    );
    expect(screen.getByText("GSTR-1 marked filed")).toBeDefined();
    expect(screen.getByRole("link", { name: "Acme Traders" }).getAttribute("href")).toBe("/b/b1");
    expect(screen.getByText("1 overdue")).toBeDefined();
    expect(screen.getByText("Up to date")).toBeDefined();
    expect(screen.getByText("3 open obligations")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
