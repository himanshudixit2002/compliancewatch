import type { BusinessPage } from "@/entities/business/types";
import type {
  Recipient,
  RecipientInput,
  RecipientPage,
  Template,
} from "@/entities/notification/types";
import type { Result } from "@/server/result";

/**
 * What the recipients page needs from the notification service: a business's recipients a page
 * at a time, one recipient, registering or replacing one whole, removing one, and the message
 * templates (the languages a recipient can be sent reminders in).
 */
export interface RecipientsPort {
  list(businessId: string, limit: number): Promise<Result<RecipientPage>>;
  get(recipientId: string): Promise<Result<Recipient>>;
  put(recipientId: string, input: RecipientInput): Promise<Result<Recipient>>;
  remove(recipientId: string): Promise<Result<void>>;
  templates(): Promise<Result<readonly Template[]>>;
}

/** And from the profile service: the tenant's businesses, by name, to choose one. */
export interface BusinessChoicePort {
  businesses(limit: number): Promise<Result<BusinessPage>>;
}
