import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { MonthCalendar, addDays, addMonths, daysInMonth, todayKey } from "./month-calendar";

function focused(): string | undefined {
  return (document.activeElement as HTMLElement | null)?.dataset.key;
}

describe("calendar helpers", () => {
  it("adds days and months across boundaries", () => {
    expect(addDays("2000-01-31", 1)).toBe("2000-02-01");
    expect(addDays("2000-03-01", -1)).toBe("2000-02-29");
    expect(addMonths({ year: 2000, month: 12 }, 1)).toEqual({ year: 2001, month: 1 });
    expect(addMonths({ year: 2000, month: 1 }, -1)).toEqual({ year: 1999, month: 12 });
    expect(daysInMonth({ year: 2000, month: 2 })).toBe(29);
    expect(daysInMonth({ year: 2001, month: 2 })).toBe(28);
  });

  it("reports today in the given time zone", () => {
    const at = new Date("2000-01-01T20:00:00Z");
    expect(todayKey("Asia/Kolkata", at)).toBe("2000-01-02");
    expect(todayKey("UTC", at)).toBe("2000-01-01");
  });
});

describe("MonthCalendar", () => {
  it("renders a labelled grid with weekday headers and one focusable cell", async () => {
    const { container } = render(
      <MonthCalendar defaultMonth={{ year: 2000, month: 1 }} selected="2000-01-15" />,
    );
    const grid = screen.getByRole("grid", { name: "January 2000" });
    expect(screen.getAllByRole("columnheader")).toHaveLength(7);
    expect(screen.getAllByRole("columnheader")[0]?.textContent).toContain("Monday");
    const cells = grid.querySelectorAll("[data-key]");
    expect(cells).toHaveLength(31);
    const focusable = grid.querySelectorAll('[data-key][tabindex="0"]');
    expect(focusable).toHaveLength(1);
    expect((focusable[0] as HTMLElement).dataset.key).toBe("2000-01-15");
    expect(focusable[0]?.getAttribute("aria-selected")).toBe("true");
    expect(
      container.querySelector('[data-slot="month-calendar"]')?.getAttribute("data-month"),
    ).toBe("2000-01");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("moves with arrows, Home, End, PageUp and PageDown and selects with Enter", async () => {
    const onSelect = vi.fn();
    const onMonthChange = vi.fn();
    render(
      <MonthCalendar
        defaultMonth={{ year: 2000, month: 1 }}
        selected="2000-01-15"
        onSelect={onSelect}
        onMonthChange={onMonthChange}
      />,
    );
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(focused()).toBe("2000-01-15");
    await userEvent.keyboard("{ArrowRight}");
    expect(focused()).toBe("2000-01-16");
    await userEvent.keyboard("{ArrowDown}");
    expect(focused()).toBe("2000-01-23");
    await userEvent.keyboard("{ArrowUp}{ArrowLeft}");
    expect(focused()).toBe("2000-01-15");
    // 15 January 2000 was a Saturday; the week starts on Monday.
    await userEvent.keyboard("{Home}");
    expect(focused()).toBe("2000-01-10");
    await userEvent.keyboard("{End}");
    expect(focused()).toBe("2000-01-16");
    await userEvent.keyboard("{PageDown}");
    expect(focused()).toBe("2000-02-16");
    expect(screen.getByRole("grid", { name: "February 2000" })).toBeDefined();
    expect(onMonthChange).toHaveBeenCalledWith({ year: 2000, month: 2 });
    await userEvent.keyboard("{Shift>}{PageUp}{/Shift}");
    expect(focused()).toBe("1999-02-16");
    await userEvent.keyboard("{PageUp}");
    expect(focused()).toBe("1999-01-16");
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("1999-01-16");
    await userEvent.keyboard(" ");
    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it("crosses the month edge with the arrow keys and clamps PageDown to the shorter month", async () => {
    render(<MonthCalendar defaultMonth={{ year: 2000, month: 1 }} selected="2000-01-31" />);
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(focused()).toBe("2000-01-31");
    await userEvent.keyboard("{PageDown}");
    expect(focused()).toBe("2000-02-29");
    await userEvent.keyboard("{ArrowRight}");
    expect(focused()).toBe("2000-03-01");
    expect(screen.getByRole("grid", { name: "March 2000" })).toBeDefined();
  });

  it("changes month with the buttons, keeps the day in range, and selects on click", async () => {
    const onSelect = vi.fn();
    const { container } = render(
      <MonthCalendar
        defaultMonth={{ year: 2000, month: 1 }}
        onSelect={onSelect}
        weekStartsOn={0}
        renderDay={(day) => (day.date === 3 ? <span>Example badge</span> : null)}
      />,
    );
    expect(screen.getAllByRole("columnheader")[0]?.textContent).toContain("Sunday");
    expect(screen.getByText("Example badge")).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("grid", { name: "February 2000" })).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByRole("grid", { name: "December 1999" })).toBeDefined();
    await userEvent.click(container.querySelector('[data-key="1999-12-25"]') as HTMLElement);
    expect(onSelect).toHaveBeenCalledWith("1999-12-25");
  });

  it("follows a controlled month and marks today", () => {
    const today = todayKey("Asia/Kolkata");
    const { container, rerender } = render(<MonthCalendar month={{ year: 2000, month: 6 }} />);
    expect(screen.getByRole("grid", { name: "June 2000" })).toBeDefined();
    const [year, month] = today.split("-").map(Number) as [number, number];
    rerender(<MonthCalendar month={{ year, month }} />);
    const cell = container.querySelector(`[data-key="${today}"]`);
    expect(cell?.getAttribute("aria-current")).toBe("date");
    expect(cell?.getAttribute("tabindex")).toBe("0");
  });
});
