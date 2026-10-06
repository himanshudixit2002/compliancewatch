"use client";

import type { Route } from "next";
import Link from "next/link";
import { useId, useRef, useState, useTransition } from "react";
import {
  Badge,
  Banner,
  ErrorState,
  MonthCalendar,
  StatusChip,
  type YearMonth,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import {
  monthName,
  monthParam,
  sameMonth,
  shiftMonthRef,
  type CalendarMonthAnswer,
  type CalendarMonthData,
} from "./calendar-shared";

export interface ObligationCalendarProps {
  /** The month the page read. */
  initial: CalendarMonthData;
  /** Reads another month on the server (a server action bound to the business). */
  load: (month: string) => Promise<CalendarMonthAnswer>;
  /** The calendar itself, without a query: a month is `?month=` on it. */
  pathname: string;
  /** The list, for everything outside the month. */
  listHref: string;
}

type Failure = Extract<CalendarMonthAnswer, { status: "error" }>;

function summary(data: CalendarMonthData): string {
  const month = monthName(data.month);
  if (data.total === 0) return t("calendar.noneThisMonth", { month });
  if (data.total === 1) return t("calendar.oneThisMonth", { month });
  return t("calendar.manyThisMonth", { month, count: data.total });
}

/**
 * The month grid of the UI kit (role="grid": arrow keys move by day and week, Page Up and Page
 * Down by month, Enter or Space selects) with each due day's count, and the chosen day's
 * obligations below it, each linking to its page. Another month is read from the server while
 * the grid keeps its place (focus stays on the day the keyboard moved to), and the address follows
 * so a reload or a shared link opens the same month; until the month arrives the page says it is
 * loading rather than showing an empty month. The plain links to the next and previous months
 * work without the grid.
 */
export function ObligationCalendar({ initial, load, pathname, listHref }: ObligationCalendarProps) {
  const id = useId();
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useState<YearMonth>(initial.month);
  const [data, setData] = useState<CalendarMonthData>(initial);
  const [day, setDay] = useState<string | null>(initial.selected);
  const [failure, setFailure] = useState<Failure | null>(null);
  const wanted = useRef<YearMonth>(initial.month);
  const loaded = sameMonth(shown, data.month);

  function changeMonth(next: YearMonth) {
    setShown(next);
    setDay(null);
    setFailure(null);
    wanted.current = next;
    const param = monthParam(next);
    window.history.replaceState(window.history.state, "", `${pathname}?month=${param}`);
    startTransition(async () => {
      const answer = await load(param);
      if (!sameMonth(wanted.current, next)) return;
      if (answer.status === "ok") {
        setData(answer.data);
        setDay(answer.data.selected);
      } else {
        setFailure(answer);
      }
    });
  }

  const chosen = day === null || !loaded ? undefined : data.days[day];
  const previous = shiftMonthRef(shown, -1);
  const next = shiftMonthRef(shown, 1);
  return (
    <div data-slot="obligation-calendar" className="flex flex-col gap-4">
      <p className="max-w-prose text-sm text-fg-muted" data-slot="calendar-summary">
        {loaded ? summary(data) : t("calendar.loadingMonth", { month: monthName(shown) })}{" "}
        <Link href={listHref as Route} className="text-primary underline underline-offset-2">
          {t("calendar.allObligations")}
        </Link>
      </p>
      {loaded && data.cut ? <Banner tone="warning" title={t("calendar.cut")} /> : null}
      {failure === null ? null : (
        <ErrorState
          title={t("calendar.loadFailed")}
          detail={failure.message}
          correlationId={failure.correlationId ?? undefined}
        />
      )}
      <MonthCalendar
        month={shown}
        onMonthChange={changeMonth}
        selected={day}
        onSelect={setDay}
        renderDay={(cell) => {
          const due = loaded ? data.days[cell.key] : undefined;
          if (due === undefined) return null;
          return (
            <span className="mt-1 flex justify-center">
              <Badge tone="warning" aria-hidden="true">
                {due.entries.length}
              </Badge>
              <span className="sr-only">{due.label}</span>
            </span>
          );
        }}
      />
      <p role="status" className="text-sm text-fg-muted" data-slot="calendar-status">
        {!loaded || pending ? t("calendar.loading") : ""}
      </p>
      <section
        aria-labelledby={`${id}-day`}
        className="flex flex-col gap-2"
        data-slot="calendar-day"
      >
        <h2 id={`${id}-day`} className="text-lg font-semibold text-fg">
          {day === null
            ? t("calendar.noDayTitle")
            : t("calendar.dayTitle", { date: formatDate(day) })}
        </h2>
        {day === null ? (
          <p className="text-sm text-fg-muted">{t("calendar.chooseDay")}</p>
        ) : chosen === undefined ? (
          <p className="text-sm text-fg-muted">
            {loaded ? t("calendar.nothingDue") : t("calendar.loading")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {chosen.entries.map((entry) => (
              <li
                key={entry.id}
                data-obligation={entry.id}
                className="flex flex-wrap items-center gap-2 text-sm"
              >
                <Link
                  href={entry.href as Route}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  {entry.title}
                </Link>
                <StatusChip
                  status={entry.status}
                  tone={entry.statusTone}
                  label={entry.statusLabel}
                />
                {entry.period === null ? null : (
                  <span className="text-xs text-fg-muted">{entry.period}</span>
                )}
                {entry.overdue ? (
                  <span className="text-xs font-medium text-danger">{t("calendar.overdue")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <nav aria-label={t("calendar.monthsLabel")}>
        <ul className="flex flex-wrap gap-4 text-sm">
          <li>
            <Link
              href={`${pathname}?month=${monthParam(previous)}` as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("calendar.previousMonth", { month: monthName(previous) })}
            </Link>
          </li>
          <li>
            <Link
              href={`${pathname}?month=${monthParam(next)}` as Route}
              className="text-primary underline-offset-2 hover:underline"
            >
              {t("calendar.nextMonth", { month: monthName(next) })}
            </Link>
          </li>
        </ul>
      </nav>
    </div>
  );
}
