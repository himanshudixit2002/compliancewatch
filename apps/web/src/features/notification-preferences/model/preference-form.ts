import { isChannel } from "@/entities/notification/mappers";
import type { Channel } from "@/entities/notification/types";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isClockTime } from "./quiet-hours";

/**
 * The notification page's two forms and their shape checks. The recipient form names the
 * channel and the number or address to look up; the preference form names the channel, whether
 * reminders are sent, the language and both ends of the quiet hours. The recipient itself is
 * never a field of the preference form: the action takes the one the page showed, from the
 * cookie that remembers it, so the form cannot be pointed at another number.
 */
export const RECIPIENT_FIELDS = { channel: "channel", recipient: "recipient" } as const;

export const PREFERENCE_FIELDS = {
  channel: "channel",
  optedIn: "opted_in",
  language: "language",
  quietStart: "quiet_hours_start",
  quietEnd: "quiet_hours_end",
} as const;

export interface PreferenceChoice {
  channel: Channel;
  optedIn: boolean;
  language: string;
  quietHoursStart: string;
  quietHoursEnd: string;
}

export type ParsedForm<T> =
  { ok: true; value: T } | { ok: false; fieldErrors?: FieldErrors; formErrors?: readonly string[] };

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export function readChannel(formData: FormData): Channel | null {
  const channel = text(formData, RECIPIENT_FIELDS.channel);
  return isChannel(channel) ? channel : null;
}

export function parseRecipientForm(
  formData: FormData,
): ParsedForm<{ channel: Channel; recipient: string }> {
  const channel = readChannel(formData);
  if (channel === null) return { ok: false, formErrors: [t("notifications.error.channel")] };
  return { ok: true, value: { channel, recipient: text(formData, RECIPIENT_FIELDS.recipient) } };
}

/** The preference form's values; `languages` are the codes the page offered. */
export function parsePreferenceForm(
  formData: FormData,
  languages: readonly string[],
): ParsedForm<PreferenceChoice> {
  const channel = readChannel(formData);
  if (channel === null) return { ok: false, formErrors: [t("notifications.error.channel")] };
  const errors: Record<string, string[]> = {};
  const opted = text(formData, PREFERENCE_FIELDS.optedIn);
  if (opted !== "in" && opted !== "out") {
    errors[PREFERENCE_FIELDS.optedIn] = [t("notifications.error.optedIn")];
  }
  const language = text(formData, PREFERENCE_FIELDS.language);
  if (!languages.includes(language)) {
    errors[PREFERENCE_FIELDS.language] = [t("notifications.error.language")];
  }
  const quietHoursStart = text(formData, PREFERENCE_FIELDS.quietStart);
  const quietHoursEnd = text(formData, PREFERENCE_FIELDS.quietEnd);
  for (const [field, value] of [
    [PREFERENCE_FIELDS.quietStart, quietHoursStart],
    [PREFERENCE_FIELDS.quietEnd, quietHoursEnd],
  ] as const) {
    if (!isClockTime(value)) errors[field] = [t("notifications.error.time")];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: { channel, optedIn: opted === "in", language, quietHoursStart, quietHoursEnd },
  };
}
