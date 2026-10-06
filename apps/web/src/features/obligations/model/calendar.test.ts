import { describe, expect, it } from "vitest";
import { listedObligationFromDto } from "@/entities/obligation/mappers";
import { NOW, dueAt, listedObligationDto } from "@/test/obligation-fixture";
import {
  calendarView,
  dueCountText,
  monthKey,
  monthLabel,
  monthWindow,
  readMonth,
  shiftMonth,
} from "./calendar";

function item(id: string, day: string | null, status: "open" | "done" = "open") {
  return listedObligationFromDto(
    listedObligationDto({
      obligation_id: `00000000-0000-4000-8000-0000000000${id}`,
      due_at: day === null ? null : dueAt(day),
      status,
      title: `Example return ${id}`,
    }),
  );
}

describe("the month in the address", () => {
  it("reads a month, else this month in India", () => {
    expect(readMonth("2000-02", NOW)).toEqual({ year: 2000, month: 2 });
    expect(readMonth(["2000-03", "2000-04"], NOW)).toEqual({ year: 2000, month: 3 });
    expect(readMonth("2000-13", NOW)).toEqual({ year: 2000, month: 1 });
    expect(readMonth("1800-01", NOW)).toEqual({ year: 2000, month: 1 });
    expect(readMonth("soon", NOW)).toEqual({ year: 2000, month: 1 });
    expect(readMonth(undefined, NOW)).toEqual({ year: 2000, month: 1 });
  });

  it("moves across years and spans the month", () => {
    expect(shiftMonth({ year: 2000, month: 1 }, -1)).toEqual({ year: 1999, month: 12 });
    expect(shiftMonth({ year: 2000, month: 12 }, 1)).toEqual({ year: 2001, month: 1 });
    expect(monthWindow({ year: 2000, month: 2 })).toEqual({ from: "2000-02-01", to: "2000-02-29" });
    expect(monthKey({ year: 2000, month: 2 })).toBe("2000-02");
    expect(monthLabel({ year: 2000, month: 2 })).toBe("February 2000");
  });
});

describe("calendarView", () => {
  it("puts each obligation on its due day in India and opens on the first due day", () => {
    const view = calendarView(
      { year: 2000, month: 1 },
      [
        item("b2", "2000-01-20"),
        item("b1", "2000-01-05", "done"),
        item("b3", "2000-01-20"),
        item("b4", null),
        item("b5", "2000-02-01"),
      ],
      { hrefFor: (id) => `/b/x/obligations/${id}`, now: NOW },
    );
    expect(Object.keys(view.days)).toEqual(["2000-01-05", "2000-01-20"]);
    expect(view.days["2000-01-20"]?.label).toBe("2 obligations due");
    expect(view.days["2000-01-05"]?.entries[0]).toMatchObject({
      title: "Example return b1",
      statusLabel: "Done",
      overdue: false,
      href: "/b/x/obligations/00000000-0000-4000-8000-0000000000b1",
    });
    expect(view.total).toBe(3);
    expect(view.selected).toBe("2000-01-05");
    expect(view.label).toBe("January 2000");
    expect(view.cut).toBe(false);
  });

  it("opens an empty month on today when today is in it, else on no day", () => {
    const options = { hrefFor: (id: string) => `/o/${id}`, now: NOW };
    expect(calendarView({ year: 2000, month: 1 }, [], options).selected).toBe("2000-01-10");
    expect(calendarView({ year: 2000, month: 3 }, [], options).selected).toBeNull();
  });

  it("counts a day's obligations in words", () => {
    expect(dueCountText(1)).toBe("1 obligation due");
    expect(dueCountText(4)).toBe("4 obligations due");
  });
});
