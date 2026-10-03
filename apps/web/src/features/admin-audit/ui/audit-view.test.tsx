import { fireEvent, render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { AuditEvent } from "../model/audit";
import { AuditView } from "./audit-view";

const EVENTS: AuditEvent[] = [
  {
    id: "ev_old",
    actor: "Kabir Shah",
    action: "tenant.exported",
    subjectType: "tenant",
    subjectId: "t_9",
    changes: [],
    at: "2026-04-10T03:30:00Z",
  },
  {
    id: "ev_late",
    actor: "Meera Iyer",
    action: "user.disabled",
    subjectType: "user",
    subjectId: "u_42",
    changes: [
      { field: "status", before: "active", after: "disabled" },
      { field: "phone", before: "+919876543210", after: null },
    ],
    // 01:30 on 11 April in IST, though still 10 April in UTC.
    at: "2026-04-10T20:00:00Z",
  },
  {
    id: "ev_rule",
    actor: "rulebook",
    action: "rule.published",
    subjectType: "rule_version",
    subjectId: "rv_7",
    changes: [{ field: "approver", before: null, after: "Kabir Shah" }],
    at: "2026-04-10T12:00:00Z",
  },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-event]")].map(
    (item) => item.getAttribute("data-event") ?? "",
  );
}

describe("AuditView", () => {
  it("lists the events newest first, worded and filed under their category", async () => {
    const { container } = render(<AuditView events={EVENTS} />);
    expect(screen.getByRole("heading", { level: 1, name: "Audit trail" })).toBeDefined();
    expect(shownIds(container)).toEqual(["ev_late", "ev_rule", "ev_old"]);

    const late = container.querySelector("[data-event='ev_late']") as HTMLElement;
    expect(late.textContent).toContain(formatDateTime("2026-04-10T20:00:00Z"));
    expect(late.querySelector("[data-slot='badge']")?.textContent).toBe("User");
    expect([...late.querySelectorAll("li")].map((item) => item.textContent)).toEqual([
      "status: active → disabled",
      "phone cleared (was +919876543210)",
    ]);
    const rule = container.querySelector("[data-event='ev_rule']") as HTMLElement;
    expect(rule.querySelector("[data-slot='badge']")?.textContent).toBe("Rule");
    expect(rule.textContent).toContain("approver set to Kabir Shah");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All categories",
      "User",
      "Tenant",
      "Obligation",
      "Rule",
      "Other",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("files each event under its IST date for the date range", () => {
    const { container } = render(<AuditView events={EVENTS} />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-04-11" } });
    expect(shownIds(container)).toEqual(["ev_late"]);
  });

  it("explains an empty trail instead of showing the filters", async () => {
    const { container } = render(<AuditView events={[]} />);
    expect(screen.getByRole("heading", { level: 2, name: "No audit events yet" })).toBeDefined();
    expect(container.querySelector("[data-slot='audit-table']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
