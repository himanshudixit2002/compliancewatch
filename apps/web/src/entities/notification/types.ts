import type { notification } from "@compliancewatch/contracts/openapi";

/**
 * A notification preference: whether a recipient (an E.164 number on WhatsApp, an address on
 * email) is opted in on a channel, in which language, and the quiet hours in IST during which
 * reminders are held. The notification service keeps one per channel and recipient; a PUT
 * replaces it. It belongs to no tenant.
 */
type Schemas = notification.components["schemas"];

export type PreferenceDto = Schemas["PreferenceOut"];
export type PreferenceInDto = Schemas["PreferenceIn"];
export type TemplateDto = Schemas["TemplateOut"];

export type Channel = Schemas["Channel"];
export type PreferenceSource = Schemas["ConsentSource"];

export interface Preference {
  channel: Channel;
  recipient: string;
  optedIn: boolean;
  source: PreferenceSource;
  language: string;
  /** HH:MM in IST. */
  quietHoursStart: string;
  quietHoursEnd: string;
  updatedAt: string;
}

export interface PreferenceChange {
  optedIn: boolean;
  source: PreferenceSource;
  /** Two letters; the service keeps its default when absent. */
  language?: string;
  quietHoursStart?: string;
  quietHoursEnd?: string;
}

/**
 * A message template as the settings page needs it: which languages a channel has templates in.
 * The body and placeholders stay on the service; `status` is Meta's approval state as recorded.
 */
export interface Template {
  key: string;
  channel: Channel;
  language: string;
  status: string;
}
