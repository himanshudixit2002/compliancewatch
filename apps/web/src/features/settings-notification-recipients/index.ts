/**
 * The notification recipients settings feature: the model for recipients and the view component.
 */
export { RecipientsView } from "./ui/recipients-view";
export type { RecipientsViewProps } from "./ui/recipients-view";
export { emptyRecipients } from "./model/recipients";
export type {
  Recipient,
  RecipientChannel,
  RecipientsView as RecipientsViewModel,
} from "./model/recipients";
