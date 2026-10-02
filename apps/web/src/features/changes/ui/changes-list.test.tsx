import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ChangeRow } from "./change-filters";
import { ChangesList } from "./changes-list";

function row(overrides: Partial<ChangeRow>): ChangeRow {
  return {
    id: "1",
    title: "GST return due date moved",
    regulator: "CBIC",
    summary: "The GSTR-3B due date moves.",
    href: "/changes/1",
    applicability: "applies",
    applicabilityLabel: "Applies to you",
    applicabilityTone: "success",
    reviewStatus: "published",
    reviewLabel: "Published",
    reviewTone: "success",
    facts: ["From CBIC", "Effective 1 Apr 2026"],
    categories: ["GST", "Returns"],
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({
    id: "2",
    title: "TDS rate change",
    regulator: "CBDT",
    href: "/changes/2",
    applicability: "pending",
    applicabilityLabel: "Pending review",
    reviewStatus: "in_review",
    reviewLabel: "In review",
    categories: [],
  }),
];

const OPTIONS = {
  applicabilityOptions: [
    { value: "applies", label: "Applies to you" },
    { value: "pending", label: "Pending review" },
  ],
  reviewOptions: [
    { value: "published", label: "Published" },
    { value: "in_review", label: "In review" },
  ],
};

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-change]")].map(
    (item) => item.getAttribute("data-change") ?? "",
  );
}

describe("ChangesList", () => {
  it("shows every change as a card with its badges, facts, categories and link", async () => {
    const { container } = render(<ChangesList rows={ROWS} {...OPTIONS} />);
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 2 changes.");
    const first = container.querySelector("[data-change='1']") as HTMLElement;
    expect(within(first).getByRole("heading", { name: "GST return due date moved" })).toBeDefined();
    expect(within(first).getByText("Effective 1 Apr 2026")).toBeDefined();
    expect(within(first).getByRole("list", { name: "Categories" }).textContent).toBe("GSTReturns");
    expect(
      within(first).getByRole("link", { name: /^View change\s*GST return due date moved$/ }),
    ).toHaveProperty("href", expect.stringContaining("/changes/1"));
    const second = container.querySelector("[data-change='2']") as HTMLElement;
    expect(within(second).queryByRole("list", { name: "Categories" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows by search, applicability and review status, and says when nothing matches", async () => {
    const user = userEvent.setup();
    const { container } = render(<ChangesList rows={ROWS} {...OPTIONS} />);

    await user.type(screen.getByLabelText("Search by title or regulator"), "cbdt");
    expect(shownIds(container)).toEqual(["2"]);
    await user.clear(screen.getByLabelText("Search by title or regulator"));

    await user.selectOptions(screen.getByLabelText("Applicability"), "applies");
    expect(shownIds(container)).toEqual(["1"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 2 changes.");

    await user.selectOptions(screen.getByLabelText("Review status"), "in_review");
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { name: "No changes match" })).toBeDefined();

    await user.selectOptions(screen.getByLabelText("Applicability"), "all");
    expect(shownIds(container)).toEqual(["2"]);
  });
});
