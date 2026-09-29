import type { ConsentRecord, ConsentSummary, NewConsent } from "@/entities/consent/types";
import type { Channel, Preference, PreferenceChange } from "@/entities/notification/types";
import type { Result } from "@/server/result";

/**
 * What the consent screens need: the identity service's consent records for the signed-in user
 * (read the states and history, append a record), and the notification service's preference
 * for a number, which an opt-in to reminders sets (docs/legal/whatsapp-consent.md: the consent
 * is recorded, then the number's preference is set to opted in).
 */
export interface ConsentsPort {
  summary(subject: string): Promise<Result<ConsentSummary>>;
  record(input: NewConsent): Promise<Result<ConsentRecord>>;
}

export interface ReminderPreferencePort {
  setPreference(
    channel: Channel,
    recipient: string,
    change: PreferenceChange,
  ): Promise<Result<Preference>>;
}
