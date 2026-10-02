import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { RiskRow } from "./risk-filters";
import { RiskTable } from "./risk-table";

function row(overrides: Partial<RiskRow>): RiskRow {
  return {
    id: "1",
    title: "Late GST filing",
    description: "Penalty and interest.",
    href: "/b/biz_1/risk/1",
    severityLabel: "High",
    severityTone: "danger",
    status: "active",
    statusLabel: "Active",
    statusTone: "danger",
    likelihood: "40%",
    identifiedAt: "10 Apr 2026",
    owner: "Asha",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    title: "Missing consent",
    status: "mitigated",
    statusLabel: "Mitigated",
    statusTone: "success",
    owner: "Ravi",
  }),
];

const TABS = [
  { value: "active", label: "Active" },
  { value: "mitigated", label: "Mitigated" },
  { value: "closed", label: "Closed" },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-risk]")].map(
    (item) => item.getAttribute("data-risk") ?? "",
  );
}

describe("RiskTable", () => {
  it("opens on all risks and links each to its page", async () => {
    const { container } = render(<RiskTable rows={ROWS} statusTabs={TABS} />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "All risks",
      "Active",
      "Mitigated",
      "Closed",
    ]);
    expect(screen.getByRole("tab", { name: "All risks" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(shownIds(container)).toEqual(["1", "2"]);
    const first = container.querySelector("[data-risk='1']") as HTMLElement;
    expect(within(first).getByRole("link", { name: "Late GST filing" })).toHaveProperty(
      "href",
      expect.stringContaining("/b/biz_1/risk/1"),
    );
    expect(first.textContent).toContain("40%");
    expect(screen.getByRole("table", { name: "Risks in the register" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("switches tabs and searches, saying when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<RiskTable rows={ROWS} statusTabs={TABS} />);

    await user.click(screen.getByRole("tab", { name: "Mitigated" }));
    expect(shownIds(container)).toEqual(["2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 2 risks.");

    await user.click(screen.getByRole("tab", { name: "All risks" }));
    await user.type(screen.getByLabelText("Search by title or owner"), "asha");
    expect(shownIds(container)).toEqual(["1"]);

    await user.click(screen.getByRole("tab", { name: "Closed" }));
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { name: "No risks match" })).toBeDefined();
  });
});
