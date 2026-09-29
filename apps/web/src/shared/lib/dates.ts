/**
 * Dates in Indian Standard Time. Services exchange ISO 8601 strings (dates as YYYY-MM-DD,
 * instants with an offset); the app renders them in Asia/Kolkata with en-IN conventions and
 * never trusts the browser's zone for a due date.
 */
export const TIME_ZONE = "Asia/Kolkata";
export const LOCALE = "en-IN";

const DAY_MS = 24 * 60 * 60 * 1000;
const DATE_KEY = /^(\d{4})-(\d{2})-(\d{2})$/;

const dateFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
});

const dateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const keyFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function isDateKey(value: string): boolean {
  const match = DATE_KEY.exec(value);
  if (match === null) return false;
  const [, y, m, d] = match.map(Number) as [number, number, number, number];
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** The calendar date (YYYY-MM-DD) of an instant in IST. */
export function istDateKey(instant: Date): string {
  return keyFormat.format(instant);
}

/** Today's IST date key; `now` is injectable for tests. */
export function todayKey(now: Date = new Date()): string {
  return istDateKey(now);
}

/** Midnight UTC of a date key, for arithmetic between keys. */
function keyToUtc(key: string): number {
  if (!isDateKey(key)) throw new Error(`not a date: ${key}`);
  const [y, m, d] = key.split("-").map(Number) as [number, number, number];
  return Date.UTC(y, m - 1, d);
}

/** Whole days from `fromKey` to `toKey` (negative when `toKey` is earlier). */
export function daysBetween(fromKey: string, toKey: string): number {
  return Math.round((keyToUtc(toKey) - keyToUtc(fromKey)) / DAY_MS);
}

export function addDaysToKey(key: string, days: number): string {
  return new Date(keyToUtc(key) + days * DAY_MS).toISOString().slice(0, 10);
}

/** "10 Apr 2026" for a date key or an instant. */
export function formatDate(value: string | Date): string {
  if (typeof value === "string" && isDateKey(value)) {
    return dateFormat.format(new Date(keyToUtc(value) + 12 * 60 * 60 * 1000));
  }
  return dateFormat.format(typeof value === "string" ? new Date(value) : value);
}

/** "10 Apr 2026, 5:30 pm IST" for an instant. */
export function formatDateTime(value: string | Date): string {
  const instant = typeof value === "string" ? new Date(value) : value;
  return `${dateTimeFormat.format(instant)} IST`;
}

export type DueRelative =
  | { kind: "today" }
  | { kind: "tomorrow" }
  | { kind: "in_days"; days: number }
  | { kind: "overdue"; days: number };

/** How a due date relates to today in IST. */
export function dueRelative(dueKey: string, now: Date = new Date()): DueRelative {
  const days = daysBetween(todayKey(now), dueKey);
  if (days === 0) return { kind: "today" };
  if (days === 1) return { kind: "tomorrow" };
  if (days > 1) return { kind: "in_days", days };
  return { kind: "overdue", days: -days };
}

/** "10 Apr 2026 (in 3 days)"; the words come from the caller so they can be translated. */
export function formatDueDate(
  dueKey: string,
  words: {
    today: string;
    tomorrow: string;
    inDays: (n: number) => string;
    overdue: (n: number) => string;
  },
  now: Date = new Date(),
): string {
  const relative = dueRelative(dueKey, now);
  const phrase =
    relative.kind === "today"
      ? words.today
      : relative.kind === "tomorrow"
        ? words.tomorrow
        : relative.kind === "in_days"
          ? words.inDays(relative.days)
          : words.overdue(relative.days);
  return `${formatDate(dueKey)} (${phrase})`;
}
