import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { reviewStatsFromDto } from "@/entities/rule-version/mappers";
import { breadcrumbsFor } from "@/shared/config/nav";
import { reviewStatsDto } from "@/test/review-task-fixture";
import { statsView } from "../model/stats";
import { StatsView } from "./stats-view";

describe("StatsView", () => {
  it("shows the counts by status and regulator, the decisions, the candidates and the time", async () => {
    const { container } = render(
      <StatsView
        title="Review stats"
        crumbs={breadcrumbsFor("admin.review.stats")}
        view={statsView(reviewStatsFromDto(reviewStatsDto()))}
        queueHref="/admin/review"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Review stats" })).toBeDefined();
    expect(container.querySelector("[data-slot='stats-status']")?.textContent).toBe(
      "Open3Claimed1Decided4Total8",
    );
    expect(container.querySelector("tr[data-regulator='example_regulator']")?.textContent).toBe(
      "example_regulator2147",
    );
    expect(container.querySelector("[data-slot='stats-decisions']")?.textContent).toBe(
      "Approved2Returned1Rejected1Decided in all4",
    );
    expect(container.querySelector("[data-slot='stats-acceptance']")?.textContent).toContain(
      "Acceptance rate: 33%",
    );
    expect(container.querySelector("[data-slot='stats-time']")?.textContent).toContain(
      "1 h 30 min",
    );
    expect(screen.getByText("Regulators with review tasks: 2")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Back to the review queue" }).getAttribute("href"),
    ).toBe("/admin/review");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when no task exists yet, and shows a failed read", () => {
    const empty = statsView(
      reviewStatsFromDto(
        reviewStatsDto({
          by_status: { open: 0, claimed: 0, decided: 0 },
          by_regulator: [],
          oldest_open_at: null,
          candidates: {
            decided: 0,
            approved: 0,
            approved_without_edits: 0,
            rejected: 0,
            acceptance_rate: null,
          },
        }),
      ),
    );
    const { rerender } = render(
      <StatsView title="Review stats" crumbs={[]} view={empty} queueHref="/admin/review" />,
    );
    expect(screen.getByText("No review task yet")).toBeDefined();
    expect(screen.getByText(/No candidate is decided yet\./)).toBeDefined();
    rerender(
      <StatsView
        title="Review stats"
        crumbs={[]}
        view={null}
        error={{ message: "Example failure", requestId: "example-id" }}
        queueHref="/admin/review"
      />,
    );
    expect(screen.getByText("Example failure")).toBeDefined();
  });
});
