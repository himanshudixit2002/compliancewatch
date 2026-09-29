"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useControllableState } from "../hooks/use-controllable-state";
import { cn } from "../lib/cn";
import { Button } from "./button";

/** A calendar month; `month` runs from 1 (January) to 12. */
export interface YearMonth {
  year: number;
  month: number;
}

/** What renderDay receives for one cell. `key` is the ISO date, YYYY-MM-DD. */
export interface CalendarDay extends YearMonth {
  key: string;
  date: number;
  today: boolean;
  selected: boolean;
}

export interface MonthCalendarProps {
  month?: YearMonth;
  defaultMonth?: YearMonth;
  onMonthChange?: (month: YearMonth) => void;
  /** The selected day as an ISO date. */
  selected?: string | null;
  onSelect?: (key: string) => void;
  /** Extra content per day cell, such as obligation badges. */
  renderDay?: (day: CalendarDay) => ReactNode;
  /** Decides which day is "today". */
  timeZone?: string;
  /** 0 for Sunday, 1 for Monday. */
  weekStartsOn?: 0 | 1;
  locale?: string;
  className?: string;
}

const DAY_MS = 86_400_000;

export function dateKey(year: number, month: number, date: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(date).padStart(2, "0")}`;
}

export function parseDateKey(key: string): { year: number; month: number; date: number } {
  const [year, month, date] = key.split("-").map(Number) as [number, number, number];
  return { year, month, date };
}

function toUtc(key: string): number {
  const { year, month, date } = parseDateKey(key);
  return Date.UTC(year, month - 1, date);
}

function fromUtc(ms: number): string {
  const d = new Date(ms);
  return dateKey(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
}

export function addDays(key: string, days: number): string {
  return fromUtc(toUtc(key) + days * DAY_MS);
}

export function addMonths({ year, month }: YearMonth, months: number): YearMonth {
  const total = year * 12 + (month - 1) + months;
  return { year: Math.floor(total / 12), month: (total % 12) + 1 };
}

export function daysInMonth({ year, month }: YearMonth): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Today's ISO date in the given time zone. */
export function todayKey(timeZone: string, now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

function monthOf(key: string): YearMonth {
  const { year, month } = parseDateKey(key);
  return { year, month };
}

function sameMonth(a: YearMonth, b: YearMonth): boolean {
  return a.year === b.year && a.month === b.month;
}

function clampDate(target: YearMonth, date: number): string {
  return dateKey(target.year, target.month, Math.min(date, daysInMonth(target)));
}

/**
 * A month grid (role="grid") with one focusable cell at a time. Arrow keys move by day and
 * week, Home and End jump within the week, PageUp and PageDown change the month (with Shift,
 * the year), Enter or Space selects. Moving past the month's edge shows the adjacent month.
 */
export function MonthCalendar({
  month: monthProp,
  defaultMonth,
  onMonthChange,
  selected = null,
  onSelect,
  renderDay,
  timeZone = "Asia/Kolkata",
  weekStartsOn = 1,
  locale = "en-IN",
  className,
}: MonthCalendarProps) {
  const today = todayKey(timeZone);
  const [month, setMonth] = useControllableState<YearMonth>({
    value: monthProp,
    defaultValue: defaultMonth ?? monthOf(selected ?? today),
    onChange: onMonthChange,
  });
  const defaultFocus = (target: YearMonth): string =>
    selected && sameMonth(monthOf(selected), target)
      ? selected
      : sameMonth(monthOf(today), target)
        ? today
        : dateKey(target.year, target.month, 1);
  const [focusedKey, setFocusedKey] = useState(() => defaultFocus(month));
  const pendingFocus = useRef(false);
  const gridRef = useRef<HTMLTableElement>(null);
  const captionId = useId();

  const visibleFocus = sameMonth(monthOf(focusedKey), month) ? focusedKey : defaultFocus(month);

  useEffect(() => {
    if (!pendingFocus.current) return;
    pendingFocus.current = false;
    gridRef.current?.querySelector<HTMLElement>(`[data-key="${visibleFocus}"]`)?.focus();
  }, [visibleFocus]);

  function moveTo(key: string) {
    pendingFocus.current = true;
    setFocusedKey(key);
    const target = monthOf(key);
    if (!sameMonth(target, month)) setMonth(target);
  }

  function showMonth(target: YearMonth) {
    setMonth(target);
    setFocusedKey(clampDate(target, parseDateKey(visibleFocus).date));
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableCellElement>, key: string) {
    const weekday = (new Date(toUtc(key)).getUTCDay() - weekStartsOn + 7) % 7;
    const moves: Record<string, () => string> = {
      ArrowLeft: () => addDays(key, -1),
      ArrowRight: () => addDays(key, 1),
      ArrowUp: () => addDays(key, -7),
      ArrowDown: () => addDays(key, 7),
      Home: () => addDays(key, -weekday),
      End: () => addDays(key, 6 - weekday),
      PageUp: () =>
        clampDate(addMonths(monthOf(key), event.shiftKey ? -12 : -1), parseDateKey(key).date),
      PageDown: () =>
        clampDate(addMonths(monthOf(key), event.shiftKey ? 12 : 1), parseDateKey(key).date),
    };
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect?.(key);
      return;
    }
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      moveTo(move());
    }
  }

  const firstWeekday =
    (new Date(Date.UTC(month.year, month.month - 1, 1)).getUTCDay() - weekStartsOn + 7) % 7;
  const total = daysInMonth(month);
  const cells: (CalendarDay | null)[] = Array.from({ length: firstWeekday }, () => null);
  for (let date = 1; date <= total; date += 1) {
    const key = dateKey(month.year, month.month, date);
    cells.push({
      key,
      year: month.year,
      month: month.month,
      date,
      today: key === today,
      selected: key === selected,
    });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks = Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));

  const weekdayFormat = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" });
  const weekdayLongFormat = new Intl.DateTimeFormat(locale, { weekday: "long", timeZone: "UTC" });
  // 2024-01-01 is a Monday; offset it to the configured first day of the week.
  const weekdays = Array.from({ length: 7 }, (_, i) => {
    const day = new Date(Date.UTC(2024, 0, 1 + ((i + weekStartsOn + 6) % 7)));
    return { short: weekdayFormat.format(day), long: weekdayLongFormat.format(day) };
  });
  const monthLabel = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(month.year, month.month - 1, 1)));
  const fullDate = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return (
    <div
      data-slot="month-calendar"
      data-month={dateKey(month.year, month.month, 1).slice(0, 7)}
      className={cn("flex flex-col gap-2", className)}
    >
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous month"
          onClick={() => showMonth(addMonths(month, -1))}
        >
          <ChevronLeftIcon aria-hidden="true" />
        </Button>
        <h2 id={captionId} aria-live="polite" className="text-sm font-semibold text-fg">
          {monthLabel}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Next month"
          onClick={() => showMonth(addMonths(month, 1))}
        >
          <ChevronRightIcon aria-hidden="true" />
        </Button>
      </div>
      <table
        ref={gridRef}
        role="grid"
        aria-labelledby={captionId}
        className="w-full table-fixed border-collapse text-sm"
      >
        <thead>
          <tr>
            {weekdays.map((weekday) => (
              <th key={weekday.long} scope="col" className="py-1 text-xs font-medium text-fg-muted">
                <span aria-hidden="true">{weekday.short}</span>
                <span className="sr-only">{weekday.long}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week, index) => (
            <tr key={index}>
              {week.map((cell, column) =>
                cell === null ? (
                  <td key={`empty-${column}`} className="p-1" />
                ) : (
                  <td
                    key={cell.key}
                    role="gridcell"
                    tabIndex={cell.key === visibleFocus ? 0 : -1}
                    aria-selected={cell.selected}
                    aria-current={cell.today ? "date" : undefined}
                    data-key={cell.key}
                    data-today={cell.today || undefined}
                    data-selected={cell.selected || undefined}
                    onKeyDown={(event) => onKeyDown(event, cell.key)}
                    onClick={() => {
                      setFocusedKey(cell.key);
                      onSelect?.(cell.key);
                    }}
                    onFocus={() => setFocusedKey(cell.key)}
                    className={cn(
                      "min-h-12 cursor-pointer rounded-md border border-transparent p-1 align-top hover:bg-fg/5 focus-visible:ring-2 focus-visible:ring-focus focus-visible:outline-none",
                      cell.today && "border-line-strong",
                      cell.selected && "bg-primary/10 border-primary",
                    )}
                  >
                    <span className="sr-only">{fullDate.format(new Date(toUtc(cell.key)))}</span>
                    <span aria-hidden="true" className="block text-right text-xs text-fg-muted">
                      {cell.date}
                    </span>
                    {renderDay?.(cell)}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
