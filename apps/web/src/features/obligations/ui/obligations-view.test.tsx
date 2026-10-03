import { render, screen } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Obligation } from "../model/obligations";
import { ObligationsView } from "./obligations-view";

/** Noon on 15 Oct 2000 in India. */
const NOW = new Date("2000-10-15T06:30:00Z");

const hrefFor = (id: string) => `/b/biz_1/obligations/${id}` as Route;

function obligation(overrides: Partial<Obligation>): Obligation {
  return {
    id: "obl_1",
    businessId: "biz_1",
    title: "File example return 1 for the month",
    status: "open",
    dueAt: "2000-10-20T18:29:59Z",
    evidenceType: "filing_acknowledgement",
    steps: ["Pay the tax due", "File example return 1"],
    ruleVersionId: "rv_1",
    decisionId: "dec_1",
    periodLabel: "2000-08",
    periodStart: "2000-08-01",
    periodEnd: "2000-09-01",
    closedAt: null,
    closedReason: null,
    ...overrides,
  };
}

const OBLIGATIONS: Obligation[] = [
  obligation({
    id: "obl_2",
    title: "Deposit example tax for September",
    status: "in_progress",
    dueAt: "2000-10-07T18:29:59Z",
    evidenceType: "",
    periodLabel: null,
    periodStart: null,
    periodEnd: null,
  }),
  obligation({ id: "obl_1" }),
  obligation({
    id: "obl_3",
    title: "File example return 2 for the month",
    status: "done",
    dueAt: "2000-10-11T18:29:59Z",
    closedAt: "2000-10-10T05:00:00Z",
    closedReason: "completed",
  }),
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

afterEach(() => {
  vi.useRealTimers();
});

describe("ObligationsView", () => {
  it("summarises the obligations and lists them, worded and linked", async () => {
    const { container } = render(
      <ObligationsView obligations={OBLIGATIONS} hrefFor={hrefFor} now={NOW} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Obligations" })).toBeDefined();
    expect(figures(container)).toEqual({
      "Total obligations": { value: "3", tone: "neutral" },
      Open: { value: "1", tone: "info" },
      "In progress": { value: "1", tone: "warning" },
      Overdue: { value: "1", tone: "danger" },
      Done: { value: "1", tone: "success" },
    });
    const rows = [...container.querySelectorAll<HTMLElement>("[data-obligation]")];
    expect(rows.map((row) => row.getAttribute("data-obligation"))).toEqual([
      "obl_2",
      "obl_1",
      "obl_3",
    ]);
    const [deposit, monthly, closed] = rows as [HTMLElement, HTMLElement, HTMLElement];
    expect(deposit.textContent).toContain("In progress");
    expect(deposit.textContent).toContain("7 Oct 2000");
    expect(deposit.textContent).toContain("Overdue by 8 days");
    expect(deposit.textContent).toContain("Not specified");
    expect(monthly.textContent).toContain("Period 2000-08: 1 Aug 2000 to 31 Aug 2000");
    expect(monthly.textContent).toContain("Due in 5 days");
    expect(monthly.textContent).toContain("Filing acknowledgement");
    expect(closed.textContent).toContain("Done");
    expect(closed.textContent).toContain("11 Oct 2000");
    expect(closed.querySelector("[data-slot='due-note']")).toBeNull();
    expect(
      screen
        .getByRole("link", { name: "File example return 2 for the month" })
        .getAttribute("href"),
    ).toBe("/b/biz_1/obligations/obl_3");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the overdue count neutral when nothing is overdue, measured against now by default", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const { container } = render(
      <ObligationsView obligations={[obligation({})]} hrefFor={hrefFor} />,
    );
    expect(figures(container).Overdue).toEqual({ value: "0", tone: "neutral" });
    expect(container.querySelector("[data-obligation='obl_1']")?.textContent).toContain(
      "Due in 5 days",
    );
  });

  it("shows the empty state when the business has no obligations", async () => {
    const { container } = render(<ObligationsView obligations={[]} hrefFor={hrefFor} now={NOW} />);
    expect(screen.getByRole("heading", { level: 2, name: "No obligations yet" })).toBeDefined();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
