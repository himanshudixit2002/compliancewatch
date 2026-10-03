import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { toNotAvailableView } from "@/entities/screen/mappers";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { NotAvailablePage } from "./not-available-page";

describe("NotAvailablePage", () => {
  it("shows the awaited routes with their owners, the roles and the guide reference", async () => {
    const screenEntry = screenById("admin.review.stats");
    const { container } = render(
      <NotAvailablePage
        view={toNotAvailableView(screenEntry)}
        crumbs={breadcrumbsFor("admin.review.stats")}
        backHref="/admin"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Review stats" })).toBeDefined();
    expect(screen.getByText("GET /v1/rulebook/review/stats")).toBeDefined();
    expect(screen.getByText("services track (WP21)")).toBeDefined();
    expect(screen.getByText("Analyst, Reviewer, Admin")).toBeDefined();
    expect(screen.getByRole("link", { name: "Back" }).getAttribute("href")).toBe("/admin");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(crumbs.textContent).toContain("Internal tools");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says no backend exists for a planned screen and shows its notes", () => {
    const view = toNotAvailableView({ ...screenById("admin.backfill"), awaits: [] });
    render(<NotAvailablePage view={view} backHref="/" />);
    expect(screen.getByText("No backend exists for this tool yet.")).toBeDefined();
    expect(screen.getByText(/make backfill/)).toBeDefined();
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull();
  });

  it("says a ready tool's backend is on main, lists what it will use and keeps its preview slot", () => {
    const { container } = render(
      <NotAvailablePage view={toNotAvailableView(screenById("admin.flags"))} backHref="/admin" />,
    );
    expect(screen.getByText(/The backend for this screen is on main/)).toBeDefined();
    expect(screen.getByText("It will use:")).toBeDefined();
    expect(screen.getByText("file packages/flags/registry.json")).toBeDefined();
    expect(screen.queryByText("This screen waits for:")).toBeNull();
    // FlagTable is named in the registry but not registered yet, so nothing renders for it.
    expect(container.querySelector("[data-slot='preview']")).toBeNull();
  });
});
