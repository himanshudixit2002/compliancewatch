import {
  MENTION_REVIEW_REASONS,
  type MentionReviewReason,
  type ReviewItem,
} from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";

/**
 * Why alignment left a mention open, in words, and where the mention is: a reason the web app
 * does not know yet is shown as sent, read as a sentence. The decisions and the reject reasons
 * are worded in ui/decision-shared.ts, which the client panel reads too.
 */
const REASONS: Readonly<Record<MentionReviewReason, MessageKey>> = {
  no_match: "entityReview.reason.noMatch",
  ambiguous_alias: "entityReview.reason.ambiguousAlias",
  empty_name: "entityReview.reason.emptyName",
  unqualified: "entityReview.reason.unqualified",
};

function isMentionReviewReason(reason: string): reason is MentionReviewReason {
  return (MENTION_REVIEW_REASONS as readonly string[]).includes(reason);
}

export function reviewReasonLabel(reason: string): string {
  return isMentionReviewReason(reason) ? t(REASONS[reason]) : humanise(reason);
}

/** The document viewer with the mention marked: `?clause_id=&start=&end=` in code points. */
export function documentMarkHref(
  item: Pick<ReviewItem, "documentId" | "clauseId" | "spanStart" | "spanEnd">,
): string {
  return withQuery(
    hrefFor(screenById("admin.rulebook.document"), { documentId: item.documentId }),
    {
      clause_id: item.clauseId,
      start: item.spanStart,
      end: item.spanEnd,
    },
  );
}
