import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listedObligationFromDto } from "@/entities/obligation/mappers";
import { NOW, dueAt, listedObligationDto } from "@/test/obligation-fixture";
import { calendarView } from "../model/calendar";
import type { CalendarPageView } from "../queries";
import type { CalendarMonthAnswer, CalendarMonthData } from "./calendar-shared";
import { CalendarView } from "./calendar-view";
import { ObligationCalendar } from "./obligation-calendar";

const HEADER = {
  crumbs: [{ id: "owner.calendar", href: "/b/x/calendar", label: "Calendar" }],
  tabs: [],
};

function page(cut = false): CalendarPageView {
  const calendar = calendarView(
    { year: 2000, month: 1 },
    [
      listedObligationDto({ due_at: dueAt("2000-01-20") }),
      listedObligationDto({
        obligation_id: "00000000-0000-4000-8000-0000000000b2",
        title: "Example return 2",
        due_at: dueAt("2000-01-05"),
      }),
    ].map(listedObligationFromDto),
    { hrefFor: (id) => `/b/x/obligations/${id}`, now: NOW },
  );
  return {
    business: { id: "x", name: "Example business", pan: "ABCDE1234F" },
    calendar: { ...calendar, cut },
  };
}

const EMPTY_FEBRUARY: CalendarMonthData = {
  month: { year: 2000, month: 2 },
  days: {},
  selected: null,
  total: 0,
  cut: false,
};

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("CalendarView", () => {
  it("marks each due day in the grid and lists the chosen day's obligations", async () => {
    const load = vi.fn(async (): Promise<CalendarMonthAnswer> => ({
      status: "ok",
      data: EMPTY_FEBRUARY,
    }));
    const { container } = render(
      <CalendarView
        title="Calendar"
        view={page()}
        header={HEADER}
        load={load}
        pageHref="/b/x/calendar"
        listHref="/b/x/obligations"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Calendar" })).toBeDefined();
    expect(screen.getByText(/2 obligations fall due in January 2000/)).toBeDefined();
    const grid = screen.getByRole("grid", { name: "January 2000" });
    const cell = grid.querySelector("[data-key='2000-01-20']");
    expect(cell?.textContent).toContain("1 obligation due");
    // It opens on the first due day, the 5th, with that day's obligation linked.
    expect(screen.getByRole("heading", { level: 2, name: "Due on 5 Jan 2000" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Example return 2" }).getAttribute("href")).toBe(
      "/b/x/obligations/00000000-0000-4000-8000-0000000000b2",
    );
    expect(screen.getByText("Overdue")).toBeDefined();
    const user = userEvent.setup();
    await user.click(cell as HTMLElement);
    expect(screen.getByRole("heading", { level: 2, name: "Due on 20 Jan 2000" })).toBeDefined();
    await user.click(grid.querySelector("[data-key='2000-01-21']") as HTMLElement);
    expect(screen.getByText("Nothing falls due on this day.")).toBeDefined();
    const months = screen.getByRole("navigation", { name: "Other months" });
    expect(
      within(months)
        .getByRole("link", { name: "Previous month: December 1999" })
        .getAttribute("href"),
    ).toBe("/b/x/calendar?month=1999-12");
    expect(screen.getByRole("complementary", { name: "Not legal advice" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    expect(load).not.toHaveBeenCalled();
  });

  it("says when the month was cut short", () => {
    render(
      <CalendarView
        title="Calendar"
        view={page(true)}
        header={HEADER}
        load={vi.fn()}
        pageHref="/b/x/calendar"
        listHref="/b/x/obligations"
      />,
    );
    expect(screen.getByText(/more obligations than the calendar reads/)).toBeDefined();
  });
});

describe("ObligationCalendar", () => {
  it("reads another month from the server, keeps the grid's place and follows it in the address", async () => {
    let resolve: (answer: CalendarMonthAnswer) => void = () => {};
    const load = vi.fn(
      (month: string) =>
        new Promise<CalendarMonthAnswer>((done) => {
          expect(month).toBe("2000-02");
          resolve = done;
        }),
    );
    render(
      <ObligationCalendar
        initial={page().calendar}
        load={load}
        pathname="/b/x/calendar"
        listHref="/b/x/obligations"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("grid", { name: "February 2000" })).toBeDefined();
    expect(screen.getByText(/Loading February 2000/)).toBeDefined();
    expect(screen.getByRole("status").textContent).toBe("Loading the month.");
    expect(window.location.search).toBe("?month=2000-02");
    resolve({
      status: "ok",
      data: { ...EMPTY_FEBRUARY, total: 0, selected: null },
    });
    await waitFor(() =>
      expect(screen.getByText(/Nothing falls due in February 2000/)).toBeDefined(),
    );
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(""));
    expect(screen.getByRole("link", { name: "Next month: March 2000" }).getAttribute("href")).toBe(
      "/b/x/calendar?month=2000-03",
    );
  });

  it("shows a month it could not read with the correlation id", async () => {
    const load = vi.fn(async (): Promise<CalendarMonthAnswer> => ({
      status: "error",
      message: "Example unavailable",
      correlationId: "req-example-8",
    }));
    render(
      <ObligationCalendar
        initial={page().calendar}
        load={load}
        pathname="/b/x/calendar"
        listHref="/b/x/obligations"
      />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Previous month" }));
    expect(await screen.findByText("The month could not be read")).toBeDefined();
    expect(screen.getByText("req-example-8")).toBeDefined();
  });
});
