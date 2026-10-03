import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TeamMember } from "../model/team";
import { TeamView } from "./team-view";

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.team", href: "/account/team", label: "Team" },
];
const TABS = [{ id: "owner.settings.team", href: "/account/team", label: "Team" }];

const MEMBERS: TeamMember[] = [
  {
    id: "u2",
    name: "Example staff member",
    email: "staff@example.com",
    roles: [],
    status: "disabled",
    joinedAt: "2000-05-02T05:00:00Z",
  },
  {
    id: "u1",
    name: "Example owner",
    email: "owner@example.com",
    roles: ["owner", "compliance_lead"],
    status: "active",
    joinedAt: "2000-04-10T05:00:00Z",
  },
];

describe("TeamView", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/account/team");
  });

  it("shows the summary and every member, active first, with roles, status and join date", async () => {
    const { container } = render(
      <TeamView title="Team" members={MEMBERS} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Team" })).toBeDefined();
    expect(screen.getByText("2 people with access")).toBeDefined();
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect([...stats].map((card) => card.textContent)).toEqual([
      "Total members2",
      "Active1",
      "Disabled1",
    ]);
    expect(stats[2]?.getAttribute("data-tone")).toBe("danger");

    const rows = container.querySelectorAll("tbody tr");
    expect([...rows].map((row) => row.getAttribute("data-member"))).toEqual(["u1", "u2"]);
    const owner = rows[0] as HTMLElement;
    expect(owner.textContent).toContain("owner@example.com");
    expect(owner.textContent).toContain("Owner");
    expect(owner.textContent).toContain("Compliance lead");
    expect(owner.textContent).toContain("10 Apr 2000");
    expect(owner.querySelector("[data-slot='status-chip']")?.textContent).toBe("Active");
    const staff = rows[1] as HTMLElement;
    expect(staff.textContent).toContain("None");
    expect(staff.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("uses a neutral disabled count when nobody is disabled", () => {
    const { container } = render(
      <TeamView title="Team" members={[MEMBERS[1] as TeamMember]} crumbs={CRUMBS} tabs={TABS} />,
    );
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect(stats[2]?.getAttribute("data-tone")).toBe("neutral");
  });

  it("explains an empty team instead of an empty table", async () => {
    const { container } = render(
      <TeamView title="Team" members={[]} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No team members" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
