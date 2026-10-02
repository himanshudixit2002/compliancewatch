import { stateOf } from "@/entities/consent/mappers";
import type { ConsentPurpose, ConsentSummary } from "@/entities/consent/types";
import { CHANNELS, recipientLabel } from "@/entities/notification/mappers";
import type { Channel, Preference, Template } from "@/entities/notification/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import { CHANNEL_PURPOSE, channelLabel, recipientFieldLabel } from "./channels";
import { languageName, languagesFor, type LanguageOption } from "./languages";
import { DEFAULT_LANGUAGE, DEFAULT_QUIET_HOURS, describeQuietHours } from "./quiet-hours";

/**
 * What the notifications page shows for each channel: whether the user's consent to that
 * channel's reminders is given, the recipient chosen on this device (none until one is
 * named), and that recipient's preference as the notification service holds it (not recorded
 * yet, recorded, or a failed read), with the form's starting values and the languages on offer.
 */
export type PreferenceRead =
  { ok: true; value: Preference | null } | { ok: false; error: ServiceErrorLike };

export interface PreferenceView {
  optedIn: boolean;
  statusLabel: string;
  language: string;
  languageLabel: string;
  quietHours: string;
  source: string;
  updatedAt: string;
}

export type ChannelState =
  | { kind: "no_recipient" }
  | { kind: "error"; error: ServiceErrorLike }
  | { kind: "not_recorded" }
  | { kind: "recorded"; preference: PreferenceView };

export interface PreferenceFormValues {
  optedIn: boolean;
  language: string;
  quietHoursStart: string;
  quietHoursEnd: string;
}

export interface ChannelView {
  channel: Channel;
  title: string;
  purpose: ConsentPurpose;
  purposeLabel: string;
  consentGiven: boolean;
  /** The recipient as a person reads it; null when none is chosen on this device. */
  recipient: string | null;
  recipientField: string;
  state: ChannelState;
  form: PreferenceFormValues;
  languages: readonly LanguageOption[];
}

export interface NotificationSettingsView {
  channels: readonly ChannelView[];
}

export interface NotificationSettingsInput {
  /** The recipient keys this device remembers for the user. */
  recipients: Partial<Record<Channel, string>>;
  /** The preference read for each channel with a recipient. */
  preferences: Partial<Record<Channel, PreferenceRead>>;
  templates: readonly Template[];
  consents: ConsentSummary;
}

export function preferenceView(preference: Preference): PreferenceView {
  return {
    optedIn: preference.optedIn,
    statusLabel: preference.optedIn ? t("notifications.optedIn") : t("notifications.optedOut"),
    language: preference.language,
    languageLabel: languageName(preference.language),
    quietHours: describeQuietHours(preference.quietHoursStart, preference.quietHoursEnd),
    source: t(`consent.source.${preference.source}`),
    updatedAt: formatDateTime(preference.updatedAt),
  };
}

function stateFor(recipient: string | undefined, read: PreferenceRead | undefined): ChannelState {
  if (recipient === undefined) return { kind: "no_recipient" };
  if (read === undefined) return { kind: "not_recorded" };
  if (!read.ok) return { kind: "error", error: read.error };
  return read.value === null
    ? { kind: "not_recorded" }
    : { kind: "recorded", preference: preferenceView(read.value) };
}

function channelView(channel: Channel, input: NotificationSettingsInput): ChannelView {
  const purpose = CHANNEL_PURPOSE[channel];
  const consentGiven = stateOf(input.consents, purpose)?.granted === true;
  const key = input.recipients[channel];
  const read = input.preferences[channel];
  const preference = read?.ok === true ? read.value : null;
  return {
    channel,
    title: channelLabel(channel),
    purpose,
    purposeLabel: t(`consent.purpose.${purpose}`),
    consentGiven,
    recipient: key === undefined ? null : recipientLabel(channel, key),
    recipientField: recipientFieldLabel(channel),
    state: stateFor(key, read),
    form:
      preference === null
        ? {
            optedIn: consentGiven,
            language: DEFAULT_LANGUAGE,
            quietHoursStart: DEFAULT_QUIET_HOURS.start,
            quietHoursEnd: DEFAULT_QUIET_HOURS.end,
          }
        : {
            optedIn: preference.optedIn,
            language: preference.language,
            quietHoursStart: preference.quietHoursStart,
            quietHoursEnd: preference.quietHoursEnd,
          },
    languages: languagesFor(channel, input.templates, preference?.language),
  };
}

export function notificationSettingsView(
  input: NotificationSettingsInput,
): NotificationSettingsView {
  return { channels: CHANNELS.map((channel) => channelView(channel, input)) };
}
