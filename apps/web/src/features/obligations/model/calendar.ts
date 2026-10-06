import type { ListedObligation } from "@/entities/obligation/types";
import { t } from "@/shared/i18n";
import { todayKey } from "@/shared/lib/dates";
import {
  monthName,
  monthParam,
  shiftMonthRef,
  type CalendarDayView,
  type CalendarEntry,
  type CalendarMonthData,
  type CalendarMonthRef,
} from "../ui/calendar-shared";
import {
  dueDay,
  isObligationOverdue,
  obligationStatusLabel,
  obligationStatusTone,
  periodText,
} from "./obligations";
import { compareByDue } from "./list";

/**
 * The calendar of a business: one month of its obligations by due day in India, the month in the
 * address (`?month=2026-10`, this month by default). The month is the due window each node's list
 * is asked for, well inside the service's 366 days, and read whole.
 */
export type CalendarMonth = CalendarMonthRef;

const MONTH = /^(\d{4})-(\d{2})$/;

export const monthKey = monthParam;

/** The month a `month` value names, else this month in India. */
export function readMonth(
  value: string | string[] | undefined,
  now: Date = new Date(),
): CalendarMonth {
  const text = Array.isArray(value) ? value[0] : value;
  const match = text === undefined ? null : MONTH.exec(text);
  if (match !== null) {
    const year = Number(match[1]);
    const month = Number(match[2]);
    if (year >= 1900 && year <= 2999 && month >= 1 && month <= 12) return { year, month };
  }
  const [year, month] = todayKey(now).split("-").map(Number) as [number, number];
  return { year, month };
}

export const shiftMonth = shiftMonthRef;

/** The month's first and last day, the due window of its read. */
export function monthWindow(month: CalendarMonth): { from: string; to: string } {
  const last = new Date(Date.UTC(month.year, month.month, 0)).getUTCDate();
  const key = monthKey(month);
  return { from: `${key}-01`, to: `${key}-${String(last).padStart(2, "0")}` };
}

/** "October 2026". */
export const monthLabel = monthName;

export interface CalendarView extends CalendarMonthData {
  label: string;
}

export function calendarView(
  month: CalendarMonth,
  items: readonly ListedObligation[],
  options: { hrefFor: (obligationId: string) => string; now?: Date },
): CalendarView {
  const now = options.now ?? new Date();
  const entries: Record<string, CalendarEntry[]> = {};
  const key = monthKey(month);
  const dated = items.filter((item) => item.dueAt !== null).sort(compareByDue);
  for (const item of dated) {
    const day = dueDay(item.dueAt as string);
    if (!day.startsWith(`${key}-`)) continue;
    (entries[day] ??= []).push({
      id: item.id,
      title: item.title,
      href: options.hrefFor(item.id),
      period: periodText(item),
      status: item.status,
      statusLabel: obligationStatusLabel(item.status),
      statusTone: obligationStatusTone(item.status),
      overdue: isObligationOverdue(item, now),
    });
  }
  const dueDays = Object.keys(entries).sort();
  const today = todayKey(now);
  const days: Record<string, CalendarDayView> = {};
  for (const day of dueDays) {
    const list = entries[day] ?? [];
    days[day] = { label: dueCountText(list.length), entries: list };
  }
  return {
    month,
    cut: false,
    label: monthLabel(month),
    days,
    total: dueDays.reduce((sum, day) => sum + (entries[day]?.length ?? 0), 0),
    selected: dueDays[0] ?? (today.startsWith(`${key}-`) ? today : null),
  };
}

/** "2 obligations due" for a day cell, read with the date by assistive technology. */
export function dueCountText(count: number): string {
  return count === 1 ? t("calendar.dueOne") : t("calendar.dueMany", { count });
}
