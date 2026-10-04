import { render, screen } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { ChangeItem } from "../model/changes";
import { ChangesView } from "./changes-view";

const hrefFor = (id: string) => `/b/biz_1/changes/${id}` as Route;

const CHANGES: ChangeItem[] = [
  {
    id: "chg_1",
    title: "Example return due date moved",
    regulator: "Example regulator",
    effectiveDate: "2000-04-01",
    publishedAt: "2000-03-10",
    applicability: "applies",
    confidence: 0.9,
    reviewStatus: "in_review",
    categories: ["Example category"],
    supersedes: "Example due dates 1999",
    summary: "x".repeat(250),
  },
  {
    id: "chg_2",
    title: "Example labour code",
    regulator: "Example ministry",
    effectiveDate: "2000-05-01",
    publishedAt: "2000-04-01",
    applicability: "unknown",
    confidence: null,
    reviewStatus: "draft",
    categories: [],
    supersedes: null,
    summary: "Example summary.",
  },
];

describe("ChangesView", () => {
  it("counts the changes and lists them, worded and linked, with the filters", async () => {
    const { container } = render(<ChangesView changes={CHANGES} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Regulatory changes" })).toBeDefined();
    expect(screen.getByText("2 changes, 1 apply to you, 1 in review.")).toBeDefined();
    expect(screen.getByText("Supersedes Example due dates 1999")).toBeDefined();
    expect(screen.getByText("Confidence 90%")).toBeDefined();
    expect(screen.getByText(`${"x".repeat(200)}…`)).toBeDefined();
    expect(container.querySelector("[data-change='chg_2']")?.textContent).toContain(
      "Not yet evaluated",
    );
    expect(
      screen
        .getByRole("link", { name: /^View change\s*Example labour code$/ })
        .getAttribute("href"),
    ).toBe("/b/biz_1/changes/chg_2");
    expect(screen.getAllByRole("option", { name: "Applies to you" })).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the empty state before any change is detected", async () => {
    const { container } = render(<ChangesView changes={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { name: "No changes yet" })).toBeDefined();
    expect(screen.getByText("0 changes, 0 apply to you, 0 in review.")).toBeDefined();
    expect(container.querySelector("[data-slot='changes-list']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
