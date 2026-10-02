import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { NO_FILTER, type CaClient } from "../model/clients";
import { CaDashboardView, type CaDashboardViewProps } from "./ca-dashboard-view";

const clients: CaClient[] = [
  {
    id: "a",
    name: "Acme Traders",
    engagementStatus: "active",
    complianceScore: 90,
    obligationsDue: 2,
    obligationsOverdue: 1,
    assignedTo: "Priya Shah",
    updatedAt: "2026-10-01T09:00:00Z",
  },
  {
    id: "b",
    name: "Bright Foods",
    engagementStatus: "pending",
    complianceScore: null,
    obligationsDue: 0,
    obligationsOverdue: 0,
    assignedTo: null,
    updatedAt: "2026-09-20T09:00:00Z",
  },
];

const base: Omit<CaDashboardViewProps, "clients" | "filter"> = {
  action: "/clients",
  clearHref: "/clients" as Route,
  clientHref: (id) => `/b/${id}` as Route,
};

describe("CaDashboardView", () => {
  it("says there are no clients yet, without a filter form", async () => {
    const { container } = render(<CaDashboardView {...base} clients={[]} filter={NO_FILTER} />);
    expect(screen.getByRole("heading", { level: 1, name: "Clients" })).toBeDefined();
    expect(screen.getByText("No clients yet")).toBeDefined();
    expect(screen.queryByRole("search")).toBeNull();
    expect(screen.getAllByText("None")).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists every client with totals, links, statuses and fallbacks", async () => {
    const { container } = render(
      <CaDashboardView {...base} clients={clients} filter={NO_FILTER} />,
    );
    expect(screen.getByText("Showing all 2 clients")).toBeDefined();
    expect(screen.getByRole("link", { name: "Acme Traders" }).getAttribute("href")).toBe("/b/a");
    const acme = container.querySelector("[data-client='a']");
    expect(acme?.textContent).toContain("Active");
    expect(acme?.textContent).toContain("Priya Shah");
    expect(acme?.querySelector(".text-danger")?.textContent).toBe("1");
    const bright = container.querySelector("[data-client='b']");
    expect(bright?.textContent).toContain("Pending");
    expect(bright?.textContent).toContain("Unassigned");
    expect(bright?.textContent).toContain("None");
    expect(screen.getAllByText("90%")).toHaveLength(2);
    expect(container.querySelector("[data-slot='stat-card'][data-tone='danger']")).not.toBeNull();
    const form = screen.getByRole("search");
    expect(form.getAttribute("action")).toBe("/clients");
    expect(screen.getByLabelText<HTMLSelectElement>("Engagement status").value).toBe("all");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the filtered count and keeps the filter in the form", () => {
    render(
      <CaDashboardView
        {...base}
        clients={clients}
        filter={{ query: "bright", status: "pending" }}
      />,
    );
    expect(screen.getByText("Showing 1 of 2 clients")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Acme Traders" })).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>("Search by name").value).toBe("bright");
    expect(screen.getByLabelText<HTMLSelectElement>("Engagement status").value).toBe("pending");
  });

  it("offers to clear a filter that matches nothing", async () => {
    const { container } = render(
      <CaDashboardView
        {...base}
        clients={[{ ...clients[1]!, obligationsOverdue: 0 }]}
        filter={{ query: "", status: "inactive" }}
      />,
    );
    expect(screen.getByText("No clients match")).toBeDefined();
    expect(screen.getByRole("link", { name: "Clear the filter" }).getAttribute("href")).toBe(
      "/clients",
    );
    expect(container.querySelector("[data-slot='stat-card'][data-tone='danger']")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
