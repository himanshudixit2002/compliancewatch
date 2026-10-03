import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { AuditRow } from "./audit-filters";
import { AuditTable } from "./audit-table";

function row(overrides: Partial<AuditRow>): AuditRow {
  return {
    id: "ev_1",
    actor: "Example analyst",
    action: "user.disabled",
    category: "user",
    categoryLabel: "User",
    subjectType: "user",
    subjectId: "u_42",
    changes: ["status: active → disabled"],
    at: "12 Apr 2000, 10:30 am IST",
    day: "2000-04-12",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "ev_1" }),
  row({
    id: "ev_2",
    actor: "rulebook",
    action: "rule.published",
    category: "rule",
    categoryLabel: "Rule",
    subjectType: "rule_version",
    subjectId: "rv_7",
    changes: ["status: in_review → published", "approver set to Example admin"],
    at: "11 Apr 2000, 4:00 pm IST",
    day: "2000-04-11",
  }),
  row({
    id: "ev_3",
    actor: "Example admin",
    action: "tenant.exported",
    category: "tenant",
    categoryLabel: "Tenant",
    subjectType: "tenant",
    subjectId: "t_9",
    changes: [],
    at: "10 Apr 2000, 9:00 am IST",
    day: "2000-04-10",
  }),
];

const CATEGORIES = [
  { value: "user", label: "User" },
  { value: "tenant", label: "Tenant" },
  { value: "rule", label: "Rule" },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-event]")].map(
    (item) => item.getAttribute("data-event") ?? "",
  );
}

describe("AuditTable", () => {
  it("lists every event with its actor, action, record and changes", async () => {
    const { container } = render(<AuditTable rows={ROWS} categoryOptions={CATEGORIES} />);
    expect(shownIds(container)).toEqual(["ev_1", "ev_2", "ev_3"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 3 of 3 events.");
    expect(screen.getByRole("table", { name: "Audit events, newest first" })).toBeDefined();

    const published = container.querySelector("[data-event='ev_2']") as HTMLElement;
    expect(published.textContent).toContain("11 Apr 2000, 4:00 pm IST");
    expect(published.textContent).toContain("rulebook");
    expect(published.textContent).toContain("rule.published");
    expect(published.querySelector("[data-slot='badge']")?.textContent).toBe("Rule");
    expect(published.textContent).toContain("rule_version");
    expect(published.textContent).toContain("rv_7");
    expect([...published.querySelectorAll("li")].map((item) => item.textContent)).toEqual([
      "status: in_review → published",
      "approver set to Example admin",
    ]);
    const exported = container.querySelector("[data-event='ev_3']") as HTMLElement;
    expect(exported.querySelector("li")).toBeNull();
    expect(exported.textContent).toContain("No fields changed");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All categories",
      "User",
      "Tenant",
      "Rule",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by search and category", async () => {
    const user = userEvent.setup();
    const { container } = render(<AuditTable rows={ROWS} categoryOptions={CATEGORIES} />);

    await user.type(screen.getByLabelText("Search by actor, action or record"), "admin");
    expect(shownIds(container)).toEqual(["ev_3"]);
    await user.clear(screen.getByLabelText("Search by actor, action or record"));

    await user.selectOptions(screen.getByLabelText("Category"), "rule");
    expect(shownIds(container)).toEqual(["ev_2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 3 events.");
  });

  it("keeps the dates in range, bounds each date input by the other and clears the filters", async () => {
    const user = userEvent.setup();
    const { container } = render(<AuditTable rows={ROWS} categoryOptions={CATEGORIES} />);
    const from = screen.getByLabelText("From") as HTMLInputElement;
    const to = screen.getByLabelText("To") as HTMLInputElement;
    expect(from.hasAttribute("max")).toBe(false);
    expect(to.hasAttribute("min")).toBe(false);

    fireEvent.change(from, { target: { value: "2000-04-11" } });
    expect(shownIds(container)).toEqual(["ev_1", "ev_2"]);
    expect(to.getAttribute("min")).toBe("2000-04-11");

    fireEvent.change(to, { target: { value: "2000-04-11" } });
    expect(shownIds(container)).toEqual(["ev_2"]);
    expect(from.getAttribute("max")).toBe("2000-04-11");

    await user.selectOptions(screen.getByLabelText("Category"), "user");
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { level: 2, name: "No events match" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Clear the filters" }));
    expect(shownIds(container)).toEqual(["ev_1", "ev_2", "ev_3"]);
    expect(from.value).toBe("");
    expect(to.value).toBe("");
    expect((screen.getByLabelText("Category") as HTMLSelectElement).value).toBe("all");
  });
});
