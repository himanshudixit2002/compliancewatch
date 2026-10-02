import type { ConsentSummary } from "@/entities/consent/types";
import type {
  Channel,
  Preference,
  PreferenceChange,
  Template,
} from "@/entities/notification/types";
import type { Result } from "@/server/result";

/**
 * What the notifications page needs: a recipient's preference on a channel (null when the
 * service has none recorded), replacing it, the message templates (for the languages each
 * channel offers), and the signed-in user's consents (an opt-in needs the channel's consent).
 */
export interface NotificationPreferencesPort {
  preference(channel: Channel, recipient: string): Promise<Result<Preference | null>>;
  save(channel: Channel, recipient: string, change: PreferenceChange): Promise<Result<Preference>>;
  templates(): Promise<Result<readonly Template[]>>;
}

export interface ConsentReadPort {
  consents(subject: string): Promise<Result<ConsentSummary>>;
}
