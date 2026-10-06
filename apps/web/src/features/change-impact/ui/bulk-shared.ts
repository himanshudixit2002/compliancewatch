/**
 * What the bulk change card panel and its server action share, in the ui directory so the client
 * panel may import it: the field the businesses travel in, the most one request names (the
 * route's limit), the businesses the page offers, and the answer, already worded.
 */
export const BULK_FIELDS = {
  businessId: "business_id",
} as const;

/** The most businesses one bulk change card names (BulkNotificationIn.business_ids). */
export const MAX_BULK_BUSINESSES = 500;

/** A business the bulk change card would name, with the words the outcome table uses. */
export interface BulkTarget {
  businessId: string;
  label: string;
}

export type BulkOutcomeName = "queued" | "duplicate" | "no_recipient" | "not_affected";

/** What a bulk change card did: the counts in a sentence, and each business it named. */
export interface BulkSummary {
  /** One sentence with every count, said whether the answer was fresh or a replay. */
  message: string;
  replayed: boolean;
  businesses: readonly {
    businessId: string;
    outcome: BulkOutcomeName;
    outcomeLabel: string;
    people: string;
  }[];
}
