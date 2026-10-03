/**
 * The notification recipients settings screen's model: people who receive notifications, with
 * their contact channels and whether they are active.
 */

export type RecipientChannel = "email" | "whatsapp" | "sms";

export interface Recipient {
  id: string;
  name: string;
  email: string;
  channels: readonly RecipientChannel[];
  active: boolean;
}

export interface RecipientsView {
  recipients: readonly Recipient[];
  totalCount: number;
}

export function emptyRecipients(): RecipientsView {
  return { recipients: [], totalCount: 0 };
}
