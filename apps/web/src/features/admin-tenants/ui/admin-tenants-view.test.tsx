import { render, screen, within } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { Tenant } from "../model/admin-tenants";
import { AdminTenantsView } from "./admin-tenants-view";

const TENANTS: Tenant[] = [
  {
    id: "t-zen",
    name: "Zen Foods",
    kind: "business",
    status: "active",
    region: "ap-south-1",
    createdAt: "2026-04-10T05:00:00Z",
  },
  {
    id: "t-rao",
    name: "Rao & Co",
    kind: "ca_firm",
    status: "deletion_requested",
    region: "ap-south-1",
    createdAt: "2026-05-02T05:00:00Z",
  },
  {
    id: "t-ops",
    name: "ComplianceWatch regulatory",
    kind: "internal",
    status: "active",
    region: "ap-south-1",
    createdAt: "2026-01-05T05:00:00Z",
  },
  {
    id: "t-old",
    name: "Old Mills",
    kind: "business",
    status: "erased",
    region: "ap-south-1",
    createdAt: "2025-11-20T05:00:00Z",
  },
];

const hrefFor = (id: string) => `/admin/tenants/${id}` as Route;
const impersonateHref = (id: string) => `/admin/tenants/${id}/impersonate` as Route;

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

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-tenant]")].map(
    (item) => item.getAttribute("data-tenant") ?? "",
  );
}

describe("AdminTenantsView", () => {
  it("summarises the tenants and lists them by name with their links", async () => {
    const { container } = render(
      <AdminTenantsView tenants={TENANTS} hrefFor={hrefFor} impersonateHref={impersonateHref} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Tenants" })).toBeDefined();
    expect(figures(container)).toEqual({
      Tenants: { value: "4", tone: "info" },
      Active: { value: "2", tone: "success" },
      "Deletion requested": { value: "1", tone: "warning" },
      Erased: { value: "1", tone: "neutral" },
    });
    expect(shownIds(container)).toEqual(["t-ops", "t-old", "t-rao", "t-zen"]);

    const zen = container.querySelector("[data-tenant='t-zen']") as HTMLElement;
    expect(within(zen).getByRole("link", { name: "Zen Foods" }).getAttribute("href")).toBe(
      "/admin/tenants/t-zen",
    );
    expect(
      within(zen)
        .getByRole("link", { name: /^Impersonate\s*Zen Foods$/ })
        .getAttribute("href"),
    ).toBe("/admin/tenants/t-zen/impersonate");
    expect(zen.textContent).toContain("Business");
    expect(zen.textContent).toContain("10 Apr 2026");
    expect(zen.querySelector("[data-slot='status-chip']")?.textContent).toBe("Active");

    for (const id of ["t-ops", "t-old", "t-rao"]) {
      const other = container.querySelector(`[data-tenant='${id}']`) as HTMLElement;
      expect(within(other).queryByRole("link", { name: /Impersonate/ })).toBeNull();
    }
    const rao = container.querySelector("[data-tenant='t-rao']") as HTMLElement;
    expect(rao.textContent).toContain("Deletion requested");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "All",
      "Business",
      "CA firm",
      "Internal (regulatory team)",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows plain names and no actions without links, and a neutral count of none", () => {
    const { container } = render(
      <AdminTenantsView
        tenants={TENANTS.filter((tenant) => tenant.status !== "deletion_requested")}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
    expect(figures(container)["Deletion requested"]).toEqual({ value: "0", tone: "neutral" });
  });

  it("explains an empty list before the first sign-up", async () => {
    const { container } = render(<AdminTenantsView tenants={[]} />);
    expect(screen.getByRole("heading", { level: 2, name: "No tenants yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
