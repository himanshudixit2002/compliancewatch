import type { Channel, Template } from "@/entities/notification/types";
import { DEFAULT_LANGUAGE } from "./quiet-hours";

/**
 * The languages a channel's reminders can be sent in: those the notification service has a
 * template in for that channel, English first, then by name. A preference's current language
 * is kept in the list even when no template uses it, so the form never drops it silently. The
 * names come from the platform's language names (Intl.DisplayNames), not from app wording.
 */
export interface LanguageOption {
  value: string;
  label: string;
}

const names = new Intl.DisplayNames(["en"], { type: "language" });

export function languageName(code: string): string {
  try {
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

export function languagesFor(
  channel: Channel,
  templates: readonly Template[],
  current?: string,
): LanguageOption[] {
  const codes = new Set(
    templates
      .filter((template) => template.channel === channel)
      .map((template) => template.language),
  );
  if (current !== undefined) codes.add(current);
  if (codes.size === 0) codes.add(DEFAULT_LANGUAGE);
  return [...codes]
    .map((code) => ({ value: code, label: languageName(code) }))
    .sort((a, b) =>
      a.value === DEFAULT_LANGUAGE
        ? -1
        : b.value === DEFAULT_LANGUAGE
          ? 1
          : a.label.localeCompare(b.label, "en"),
    );
}
