import { t } from "@/shared/i18n";

/**
 * Quiet hours: a window in Indian Standard Time during which the notification service holds a
 * reminder and sends it when the window ends. A window may cross midnight (21:00 to 08:00), and
 * a window whose start equals its end holds nothing. Times are HH:MM on the 24-hour clock, the
 * format the service validates; it keeps a window only when both ends are sent, so the form
 * always sends both. Without a preference the service's own defaults apply: English and 21:00
 * to 08:00 (services/notification, domain/preferences.py).
 */
export const DEFAULT_QUIET_HOURS = { start: "21:00", end: "08:00" } as const;
export const DEFAULT_LANGUAGE = "en";

const CLOCK_TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

export function isClockTime(value: string): boolean {
  return CLOCK_TIME.test(value);
}

/** "22:00 to 07:00 IST, across midnight"; "No quiet hours" when the ends are equal. */
export function describeQuietHours(start: string, end: string): string {
  if (start === end) return t("notifications.quiet.none");
  return start < end
    ? t("notifications.quiet.window", { start, end })
    : t("notifications.quiet.overnight", { start, end });
}
