import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { Reminder } from "../model/reminders";
import { RemindersView } from "./reminders-view";

const ITEMS: Reminder[] = [
  {
    id: "r-late",
    title: "GSTR-1 for September",
    description: null,
    dueAt: "2026-10-11T12:30:00Z",
    status: "upcoming",
    channel: "email",
    obligationId: null,
  },
  {
    id: "r-early",
    title: "TDS payment for September",
    description: "Deposit the tax deducted in September.",
    dueAt: "2026-10-07T12:30:00Z",
    status: "overdue",
    channel: "whatsapp",
    obligationId: "ob-1",
  },
];

const obligationHref = (id: string) => `/b/biz-1/obligations/${id}` as Route;

describe("RemindersView", () => {
  it("lists reminders earliest due first with status, channel and obligation link", async () => {
    const { container } = render(<RemindersView items={ITEMS} obligationHref={obligationHref} />);
    expect(screen.getByRole("heading", { level: 1, name: "Reminders" })).toBeDefined();
    const events = [...container.querySelectorAll("[data-slot='timeline'] > li")];
    expect(events.map((event) => event.getAttribute("data-tone"))).toEqual(["danger", "info"]);
    const [first, second] = events as HTMLElement[];
    expect(first?.textContent).toContain("TDS payment for September");
    expect(first?.textContent).toContain("Overdue");
    expect(first?.textContent).toContain("WhatsApp");
    expect(first?.textContent).toContain("Deposit the tax deducted in September.");
    expect(first?.querySelector("time")?.getAttribute("dateTime")).toBe("2026-10-07T12:30:00Z");
    expect(first?.querySelector("time")?.textContent).toBe(formatDateTime("2026-10-07T12:30:00Z"));
    expect(second?.textContent).toContain("Email");
    expect(second?.querySelector("a")).toBeNull();
    expect(screen.getByRole("link", { name: "Open the obligation" }).getAttribute("href")).toBe(
      "/b/biz-1/obligations/ob-1",
    );
    expect(screen.getByRole("status").textContent).toContain("Overdue reminders: 1");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows no obligation links without an href builder and no warning when none is overdue", () => {
    const calm = ITEMS.map((item) => ({ ...item, status: "sent" as const }));
    render(<RemindersView items={calm} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("list", { name: "Reminders by due date" })).toBeDefined();
  });

  it("shows an empty state when nothing is scheduled", async () => {
    const { container } = render(<RemindersView items={[]} />);
    expect(container.querySelector("[data-slot='timeline']")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No reminders" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
