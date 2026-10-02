import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { AdminMember } from "../model/admin-team";
import { AdminTeamView } from "./admin-team-view";

const MEMBERS: AdminMember[] = [
  {
    id: "u1",
    name: "Meera Iyer",
    email: "meera@example.com",
    roles: ["admin", "reviewer"],
    status: "active",
    joinedAt: "2026-02-01T05:00:00Z",
  },
  {
    id: "u2",
    name: "Kabir Shah",
    email: "kabir@example.com",
    roles: ["analyst"],
    status: "disabled",
    joinedAt: "2026-03-03T05:00:00Z",
  },
];

describe("AdminTeamView", () => {
  it("shows the summary, the add link and the users with their wording", async () => {
    const { container } = render(
      <AdminTeamView title="Internal users" members={MEMBERS} addHref="/admin/team" />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Internal users" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Add a user" }).getAttribute("href")).toBe(
      "/admin/team",
    );
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect([...stats].map((card) => card.textContent)).toEqual([
      "Users2",
      "Active1",
      "Disabled1",
      "Admins1",
    ]);
    expect(stats[2]?.getAttribute("data-tone")).toBe("danger");
    const meera = container.querySelector("[data-member='u1']") as HTMLElement;
    expect(meera.textContent).toContain("Admin");
    expect(meera.textContent).toContain("Reviewer");
    expect(meera.textContent).toContain("1 Feb 2026");
    expect(meera.querySelector("[data-slot='status-chip']")?.textContent).toBe("Active");
    const kabir = container.querySelector("[data-member='u2']") as HTMLElement;
    expect(kabir.querySelector("[data-slot='status-chip']")?.textContent).toBe("Disabled");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All roles",
      "Analyst",
      "Reviewer",
      "Admin",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves out the add link when no href is given, and keeps a zero disabled count neutral", () => {
    const { container } = render(
      <AdminTeamView title="Internal users" members={[MEMBERS[0] as AdminMember]} />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    const stats = container.querySelectorAll("[data-slot='stat-card']");
    expect(stats[2]?.getAttribute("data-tone")).toBe("neutral");
  });

  it("explains an empty list instead of showing filters", async () => {
    const { container } = render(<AdminTeamView title="Internal users" members={[]} />);
    expect(screen.getByRole("heading", { level: 2, name: "No internal users" })).toBeDefined();
    expect(container.querySelector("[data-slot='member-table']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
