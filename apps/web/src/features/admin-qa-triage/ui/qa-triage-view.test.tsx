import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import type { TriageItem } from "../model/qa-triage";
import { AdminQaTriageView } from "./qa-triage-view";

const hrefFor = (id: string) => `/admin/qa-triage/${id}` as Route;

const ITEMS: TriageItem[] = [
  {
    id: "tri_closed",
    question: "Who files ITC-04?",
    category: "Job work",
    reason: "thumbs_down",
    priority: "high",
    status: "closed",
    assignee: "Asha Rao",
    createdAt: "2026-09-28T05:00:00Z",
  },
  {
    id: "tri_low",
    question: "Is TDS due on rent?",
    category: "TDS",
    reason: "not_covered",
    priority: "low",
    status: "open",
    assignee: null,
    createdAt: "2026-09-29T05:00:00Z",
  },
  {
    id: "tri_high",
    question: "When is GSTR-3B due for March?",
    category: "GST returns",
    reason: "not_covered",
    priority: "high",
    status: "open",
    assignee: "Ravi Kumar",
    createdAt: "2026-10-01T05:00:00Z",
  },
];

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

describe("AdminQaTriageView", () => {
  it("counts the queue and lists it open first, most urgent at the top, worded and linked", async () => {
    const { container } = render(<AdminQaTriageView items={ITEMS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Q&A triage" })).toBeDefined();
    expect(figures(container)).toEqual({
      Questions: { value: "3", tone: "info" },
      Open: { value: "2", tone: "warning" },
      Closed: { value: "1", tone: "success" },
    });

    const rows = [...container.querySelectorAll<HTMLElement>("[data-triage]")];
    expect(rows.map((row) => row.getAttribute("data-triage"))).toEqual([
      "tri_high",
      "tri_low",
      "tri_closed",
    ]);
    expect(rows[0]?.textContent).toContain("Ravi Kumar");
    expect(rows[1]?.textContent).toContain("Unassigned");
    expect(rows[1]?.textContent).toContain("Low");
    expect(rows[1]?.textContent).toContain(formatDateTime("2026-09-29T05:00:00Z"));
    expect(rows[2]?.textContent).toContain("Marked unhelpful");
    expect(rows[2]?.querySelector("[data-slot='status-chip']")?.textContent).toBe("Closed");
    expect(screen.getByRole("link", { name: "Who files ITC-04?" }).getAttribute("href")).toBe(
      "/admin/qa-triage/tri_closed",
    );
    expect(screen.getAllByRole("option", { name: "Marked unhelpful" })).toHaveLength(1);
    expect(screen.getAllByRole("option", { name: "Closed" })).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves the questions unlinked without a review page and the open count neutral at zero", () => {
    const closed = ITEMS.filter((item) => item.status === "closed");
    const { container } = render(<AdminQaTriageView items={closed} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Who files ITC-04?")).toBeDefined();
    expect(figures(container).Open).toEqual({ value: "0", tone: "neutral" });
  });

  it("shows the empty state when nothing waits for triage", async () => {
    const { container } = render(<AdminQaTriageView items={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 2, name: "Nothing to triage" })).toBeDefined();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(container.querySelector("[data-slot='triage-table']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
