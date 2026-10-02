import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ReviewRow } from "./review-filters";
import { ReviewQueueTable } from "./review-queue-table";

function row(overrides: Partial<ReviewRow>): ReviewRow {
  return {
    id: "1",
    title: "Turnover band changed",
    description: "From 1-5 Cr to 5-20 Cr.",
    href: "/admin/review/1",
    type: "attribute_change",
    typeLabel: "Attribute change",
    status: "pending",
    statusLabel: "Pending",
    statusTone: "warning",
    priorityLabel: "High",
    priorityTone: "danger",
    businessName: "Acme Traders",
    submittedBy: "Asha",
    submittedAt: "10 Apr 2026, 5:30 pm IST",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    title: "Consent withdrawn",
    href: "/admin/review/2",
    type: "consent_change",
    typeLabel: "Consent",
    businessName: "Beta Foods",
  }),
  row({
    id: "3",
    title: "Evidence uploaded",
    status: "approved",
    statusLabel: "Approved",
    statusTone: "success",
    businessName: "Beta Foods",
  }),
];

const PROPS = {
  rows: ROWS,
  statusTabs: [
    { value: "pending", label: "Pending" },
    { value: "approved", label: "Approved" },
    { value: "rejected", label: "Rejected" },
  ],
  typeOptions: [
    { value: "attribute_change", label: "Attribute change" },
    { value: "consent_change", label: "Consent" },
  ],
  initialStatus: "pending",
};

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-review]")].map(
    (item) => item.getAttribute("data-review") ?? "",
  );
}

describe("ReviewQueueTable", () => {
  it("opens on the initial tab and links each item to its page", async () => {
    const { container } = render(<ReviewQueueTable {...PROPS} />);
    expect(screen.getByRole("tab", { name: "Pending" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Pending",
      "Approved",
      "Rejected",
      "All",
    ]);
    expect(shownIds(container)).toEqual(["1", "2"]);
    const first = container.querySelector("[data-review='1']") as HTMLElement;
    expect(within(first).getByRole("link", { name: "Turnover band changed" })).toHaveProperty(
      "href",
      expect.stringContaining("/admin/review/1"),
    );
    expect(first.textContent).toContain("From 1-5 Cr to 5-20 Cr.");
    expect(first.textContent).toContain("Asha");
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 3 items.");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("switches tabs and narrows by type and search, saying when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<ReviewQueueTable {...PROPS} />);

    await user.click(screen.getByRole("tab", { name: "Approved" }));
    expect(shownIds(container)).toEqual(["3"]);

    await user.click(screen.getByRole("tab", { name: "All" }));
    expect(shownIds(container)).toEqual(["1", "2", "3"]);

    await user.type(screen.getByLabelText("Search by title or business"), "beta");
    expect(shownIds(container)).toEqual(["2", "3"]);

    await user.selectOptions(screen.getByLabelText("Type"), "consent_change");
    expect(shownIds(container)).toEqual(["2"]);

    await user.click(screen.getByRole("tab", { name: "Rejected" }));
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { name: "No items match" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
