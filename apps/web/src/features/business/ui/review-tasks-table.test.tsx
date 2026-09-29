import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ReviewTasksTable, type ReviewTasksTableRow } from "./review-tasks-table";

const ROWS: ReviewTasksTableRow[] = [
  {
    id: "t-1",
    attributeLabel: "Example flag",
    reasonLabel: "Example reason",
    asOfFy: null,
    openedAt: "3 Jan 2000, 5:30 am IST",
    open: true,
    statusLabel: "Open",
    nodeName: "Example registration",
  },
  {
    id: "t-2",
    attributeLabel: "Example band",
    reasonLabel: "Example other reason",
    asOfFy: "2000-01",
    openedAt: "2 Jan 2000, 5:30 am IST",
    open: false,
    statusLabel: "Closed",
    nodeName: "Example business",
  },
];

describe("ReviewTasksTable", () => {
  it("lists each task with its reason, year, time and node under a caption", async () => {
    const { container } = render(<ReviewTasksTable rows={ROWS} caption="Example tasks" />);
    expect(screen.getByRole("table", { name: "Example tasks" })).toBeDefined();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Attribute",
      "Why it is open",
      "Financial year",
      "Opened",
      "On",
    ]);
    expect(screen.getByText("Any year")).toBeDefined();
    expect(screen.getByText("2000-01")).toBeDefined();
    expect(container.querySelector("[data-task-id='t-1']")?.textContent).toContain(
      "Example reason",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("adds the status column on request", async () => {
    const { container } = render(
      <ReviewTasksTable rows={ROWS} caption="Example tasks" showStatus />,
    );
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeDefined();
    expect(screen.getByText("Open")).toBeDefined();
    expect(screen.getByText("Closed")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
