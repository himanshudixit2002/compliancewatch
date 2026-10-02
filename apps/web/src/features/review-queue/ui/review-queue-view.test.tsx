import { render, screen } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ReviewItem } from "../model/review-queue";
import { ReviewQueueView } from "./review-queue-view";

const hrefFor = (id: string) => `/admin/review/${id}` as Route;

const ITEMS: ReviewItem[] = [
  {
    id: "rev_1",
    type: "obligation_review",
    title: "New TDS obligation",
    description: "Monthly TDS deposit.",
    status: "pending",
    priority: "medium",
    submittedBy: "Asha",
    submittedAt: "2026-04-10T12:00:00Z",
    businessName: "Acme Traders",
  },
  {
    id: "rev_2",
    type: "evidence_review",
    title: "Challan uploaded",
    description: "March challan.",
    status: "rejected",
    priority: "low",
    submittedBy: "Ravi",
    submittedAt: "2026-04-11T12:00:00Z",
    businessName: "Beta Foods",
  },
];

function figure(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("ReviewQueueView", () => {
  it("counts the queue by status and shows the pending items, worded and linked", async () => {
    const { container } = render(<ReviewQueueView items={ITEMS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Review queue" })).toBeDefined();
    expect(figure(container, "Total items")).toBe("2");
    expect(figure(container, "Pending")).toBe("1");
    expect(figure(container, "Approved")).toBe("0");
    expect(figure(container, "Rejected")).toBe("1");
    const pending = container.querySelector("[data-review='rev_1']") as HTMLElement;
    expect(pending.textContent).toContain("Obligation");
    expect(pending.textContent).toContain("Medium");
    expect(pending.textContent).toContain("10 Apr 2026, 5:30 pm IST");
    expect(screen.getByRole("link", { name: "New TDS obligation" }).getAttribute("href")).toBe(
      "/admin/review/rev_1",
    );
    expect(container.querySelector("[data-review='rev_2']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the empty state when nothing was submitted", async () => {
    const { container } = render(<ReviewQueueView items={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { name: "Nothing to review" })).toBeDefined();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
