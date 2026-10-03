import { t } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";

/**
 * The activity screen's model: the account's audit trail as `GET /v1/identity/audit` (awaited)
 * would return it, one entry per change: who made it, what they did, what it applied to and
 * when. The trail is append-only; the page reads it and never changes it.
 */
export interface ActivityEntry {
  id: string;
  /** Who acted, by name; null when the service acted on its own, such as a scheduled change. */
  actor: string | null;
  /** What was done, as the trail records it: "consent_withdrawn" or "consent.withdrawn". */
  action: string;
  /** What it was done to, as the service words it: "WhatsApp reminders", "Asha Rao". */
  subject: string;
  /** An ISO instant. */
  at: string;
}

/** The action as a sentence: "consent_withdrawn" or "consent.withdrawn" is "Consent withdrawn". */
export function actionLabel(action: string): string {
  return humanise(action.replaceAll(".", " "));
}

/** The person who acted, or the service when nobody did. */
export function actorLabel(actor: string | null): string {
  return actor ?? t("settingsActivity.automatic");
}

/** Newest first; entries at the same instant keep their order. */
export function newestFirst(entries: readonly ActivityEntry[]): ActivityEntry[] {
  return [...entries].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}
