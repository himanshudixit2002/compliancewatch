import { isE164, isEmailAddress } from "@/shared/lib/identifiers";
import type {
  Channel,
  Preference,
  PreferenceChange,
  PreferenceDto,
  PreferenceInDto,
  Template,
  TemplateDto,
} from "./types";

/** The channels a preference is kept for, in the order the settings page shows them. */
export const CHANNELS: readonly Channel[] = ["whatsapp", "email"];

export function isChannel(value: string): value is Channel {
  return (CHANNELS as readonly string[]).includes(value);
}

/**
 * How a recipient is keyed on the notification service. WhatsApp reports a number as its
 * digits without the plus (the bot's opt-ins and the seed use that form), so a WhatsApp
 * preference is keyed that way; an email address is keyed lowercased.
 */
const WHATSAPP_KEY = /^[1-9][0-9]{7,14}$/;

/** "+919800000001" -> "919800000001"; throws for a value that is not E.164. */
export function whatsappKeyOf(e164: string): string {
  if (!isE164(e164)) throw new Error("not an E.164 number");
  return e164.slice(1);
}

/** "919800000001" -> "+919800000001", for a field or a sentence. */
export function whatsappNumberOf(key: string): string {
  return `+${key}`;
}

export function emailKeyOf(address: string): string {
  return address.trim().toLowerCase();
}

/** True when the value is a key the service uses for the channel. */
export function isRecipientKey(channel: Channel, value: string): boolean {
  if (channel === "whatsapp") return WHATSAPP_KEY.test(value);
  return isEmailAddress(value) && value === emailKeyOf(value);
}

/** The recipient as a person reads it: the number with its plus, or the address. */
export function recipientLabel(channel: Channel, key: string): string {
  return channel === "whatsapp" ? whatsappNumberOf(key) : key;
}

export function preferenceFromDto(dto: PreferenceDto): Preference {
  return {
    channel: dto.channel,
    recipient: dto.recipient,
    optedIn: dto.opted_in,
    source: dto.source,
    language: dto.language,
    quietHoursStart: dto.quiet_hours_start,
    quietHoursEnd: dto.quiet_hours_end,
    updatedAt: dto.updated_at,
  };
}

/** The PUT body; the language and the quiet hours travel only when set. */
export function preferenceChangeToDto(change: PreferenceChange): PreferenceInDto {
  const dto: PreferenceInDto = { opted_in: change.optedIn, source: change.source };
  if (change.language !== undefined) dto.language = change.language;
  if (change.quietHoursStart !== undefined) dto.quiet_hours_start = change.quietHoursStart;
  if (change.quietHoursEnd !== undefined) dto.quiet_hours_end = change.quietHoursEnd;
  return dto;
}

export function templateFromDto(dto: TemplateDto): Template {
  return { key: dto.key, channel: dto.channel, language: dto.language, status: dto.status };
}
