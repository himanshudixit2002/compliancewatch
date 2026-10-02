import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { MemberRow } from "./member-filter";
import { MemberTable } from "./member-table";

const ROWS: MemberRow[] = [
  {
    id: "u1",
    name: "Meera Iyer",
    email: "meera@example.com",
    roles: [{ value: "admin", label: "Admin", tone: "warning" }],
    status: { value: "active", label: "Active", tone: "success" },
    joined: "1 Feb 2026",
  },
  {
    id: "u2",
    name: "Kabir Shah",
    email: "kabir@example.com",
    roles: [],
    status: { value: "disabled", label: "Disabled", tone: "danger" },
    joined: "3 Mar 2026",
  },
];
const ROLES = [{ value: "admin", label: "Admin" }];

function shownIds(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll("tbody tr")].map((r) => r.getAttribute("data-member"));
}

describe("MemberTable", () => {
  it("lists every member with roles, status and join date", async () => {
    const { container } = render(<MemberTable rows={ROWS} roles={ROLES} />);
    expect(shownIds(container)).toEqual(["u1", "u2"]);
    expect(screen.getByText("Showing 2 of 2 users")).toBeDefined();
    const meera = container.querySelector("[data-member='u1']") as HTMLElement;
    expect(meera.textContent).toContain("Admin");
    expect(meera.textContent).toContain("1 Feb 2026");
    expect(meera.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "success",
    );
    const kabir = container.querySelector("[data-member='u2']") as HTMLElement;
    expect(kabir.textContent).toContain("None");
    expect(kabir.querySelector("[data-slot='status-chip']")?.textContent).toBe("Disabled");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All roles",
      "Admin",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("filters by search text and by role, and clears both from the no-match state", async () => {
    const user = userEvent.setup();
    const { container } = render(<MemberTable rows={ROWS} roles={ROLES} />);

    await user.type(screen.getByLabelText("Search by name or email"), "kabir");
    expect(shownIds(container)).toEqual(["u2"]);
    expect(screen.getByText("Showing 1 of 2 users")).toBeDefined();

    await user.selectOptions(screen.getByLabelText("Role"), "admin");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { level: 3, name: "No users match" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Clear the filters" }));
    expect(shownIds(container)).toEqual(["u1", "u2"]);
    expect((screen.getByLabelText("Search by name or email") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Role") as HTMLSelectElement).value).toBe("all");

    await user.selectOptions(screen.getByLabelText("Role"), "admin");
    expect(shownIds(container)).toEqual(["u1"]);
  });
});
