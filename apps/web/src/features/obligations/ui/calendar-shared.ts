import type { Tone } from "@compliancewatch/ui";

/**
 * What the calendar's client grid receives, in the ui directory so it may import it: each due
 * day's obligations, already worded, and the month in the address's form.
 */
export interface CalendarMonthRef {
  year: number;
  /** 1 (January) to 12. */
  month: number;
}

export interface CalendarEntry {
  id: string;
  title: string;
  href: string;
  period: string | null;
  status: string;
  statusLabel: string;
  statusTone: Tone;
  overdue: boolean;
}

export interface CalendarDayView {
  /** "2 obligations due", read after the date in the day's cell. */
  label: string;
  entries: readonly CalendarEntry[];
}

/** "2026-10": the `month` value of the calendar's address. */
export function monthParam({ year, month }: CalendarMonthRef): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}`;
}

export function sameMonth(a: CalendarMonthRef, b: CalendarMonthRef): boolean {
  return a.year === b.year && a.month === b.month;
}

/** One month of the calendar as the server read it. */
export interface CalendarMonthData {
  month: CalendarMonthRef;
  /** Date keys to the obligations due that day, in due order. */
  days: Readonly<Record<string, CalendarDayView>>;
  /** The day the month opens on: the first with an obligation, else today when in the month. */
  selected: string | null;
  /** How many obligations fall due in the month. */
  total: number;
  /** True when a node held more of the month than the read takes. */
  cut: boolean;
}

/** What asking the server for another month answers. */
export type CalendarMonthAnswer =
  | { status: "ok"; data: CalendarMonthData }
  | { status: "error"; message: string; correlationId: string | null };

/** "October 2026", as the grid's own heading says it. */
export function monthName({ year, month }: CalendarMonthRef): string {
  return new Intl.DateTimeFormat("en-IN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

export function shiftMonthRef({ year, month }: CalendarMonthRef, by: number): CalendarMonthRef {
  const total = year * 12 + (month - 1) + by;
  return { year: Math.floor(total / 12), month: (total % 12) + 1 };
}
