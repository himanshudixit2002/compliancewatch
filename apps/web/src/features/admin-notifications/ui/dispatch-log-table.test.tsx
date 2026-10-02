import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { DispatchLogTable } from "./dispatch-log-table";
import type { DispatchRow } from "./dispatch-rows";

const ROWS: DispatchRow[] = [
  {
    id: "d1",
    occasionLabel: "Reminder",
    channelLabel: "WhatsApp",
    recipient: "+919876543210",
    state: "delivered",
    stateLabel: "Delivered",
    tone: "success",
    bucket: "delivered",
    createdLabel: "1 Oct 2026, 10:30 am IST",
  },
  {
    id: "d2",
    occasionLabel: "Change card",
    channelLabel: "Email",
    recipient: "owner@example.com",
    state: "queued",
    stateLabel: "Queued",
    tone: "neutral",
    bucket: "pending",
    createdLabel: "2 Oct 2026, 9:00 am IST",
  },
];

function shownIds(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll("[data-dispatch]")].map((node) =>
    node.getAttribute("data-dispatch"),
  );
}

describe("DispatchLogTable", () => {
  it("shows every dispatch, then narrows by outcome", async () => {
    const user = userEvent.setup();
    const { container } = render(<DispatchLogTable rows={ROWS} />);
    expect(shownIds(container)).toEqual(["d1", "d2"]);
    expect(screen.getByText("Showing 2 of 2 latest dispatches.")).toBeDefined();
    const chip = container.querySelector("[data-dispatch='d1'] [data-slot='status-chip']");
    expect(chip?.getAttribute("data-tone")).toBe("success");
    expect(chip?.textContent).toBe("Delivered");
    expect(await runAxe(container)).toHaveNoViolations();

    const show = screen.getByRole("combobox", { name: "Show" });
    await user.selectOptions(show, "pending");
    expect(shownIds(container)).toEqual(["d2"]);

    await user.selectOptions(show, "failed");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "No dispatch matches" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.selectOptions(show, "all");
    expect(shownIds(container)).toEqual(["d1", "d2"]);
  });

  it("ignores a value that is not one of the filters", () => {
    const { container } = render(<DispatchLogTable rows={ROWS} />);
    const show = screen.getByRole("combobox", { name: "Show" });
    fireEvent.change(show, { target: { value: "bounced" } });
    expect(shownIds(container)).toEqual(["d1", "d2"]);
  });
});
