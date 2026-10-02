import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { businessFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, REVIEW_TASK_DTO } from "@/test/business-fixture";
import { reviewTasksView } from "../model/business-pages";
import { ReviewTasksView } from "./review-tasks-view";

const BUSINESS = businessFromDto(BUSINESS_DTO);

describe("ReviewTasksView", () => {
  it("lists every task with its status and counts the open ones", async () => {
    const view = reviewTasksView(BUSINESS, [
      reviewTaskFromDto(REVIEW_TASK_DTO),
      reviewTaskFromDto({ ...REVIEW_TASK_DTO, id: "closed", open: false }),
    ]);
    const { container } = render(
      <ReviewTasksView title="Review tasks" view={view} header={{ crumbs: [], tabs: [] }} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Review tasks" })).toBeDefined();
    expect(screen.getByText("1 open of 2.")).toBeDefined();
    expect(screen.getByRole("table", { name: "Review tasks on this business" })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the list is empty", async () => {
    const { container } = render(
      <ReviewTasksView
        title="Review tasks"
        view={reviewTasksView(BUSINESS, [])}
        header={{ crumbs: [], tabs: [] }}
      />,
    );
    expect(screen.getByRole("heading", { name: "No review task" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
