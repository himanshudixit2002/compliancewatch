"use server";

import { idempotencyHeaders } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { isProblem, toActionProblem, toActionState } from "@/server/result";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, actionSuccess, type ActionState } from "@/shared/lib/action-state";
import { isHexUuid, isUuid } from "@/shared/lib/identifiers";
import { changeImpactGateway } from "./gateway";
import { bulkSummary } from "./model/impact";
import { BULK_FIELDS, MAX_BULK_BUSINESSES, type BulkSummary } from "./ui/bulk-shared";

/**
 * Sends the change card to the affected clients' own people: the screen's gate again (a CA
 * firm's admin or staff), the businesses the page rendered into the form (ids, each once, at most
 * 500; the service treats another tenant's business as not affected), and the notification
 * service's bulk route with the Idempotency-Key the page minted (`notification.bulk`). A repeat
 * with the same key gets the first answer back and the panel says nothing was sent twice. With the
 * service's switch off (503 `notification-bulk-disabled`) nothing is sent, and the panel says so
 * in those words; no web flag hides the panel, since the switch is the service's.
 */
const SCREEN = screenById("ca.change-impact");

const BULK_DISABLED = "notification-bulk-disabled";

export async function sendChangeCards(
  ruleVersionId: string,
  _state: ActionState<BulkSummary>,
  formData: FormData,
): Promise<ActionState<BulkSummary>> {
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) return actionFailure(t("changeImpact.error.version"));
  const ids = formData
    .getAll(BULK_FIELDS.businessId)
    .map((value) => (typeof value === "string" ? value.trim().toLowerCase() : ""));
  const unique = [...new Set(ids)];
  if (unique.length === 0 || unique.some((id) => !isUuid(id))) {
    return actionFailure(t("changeImpact.error.businesses"));
  }
  if (unique.length > MAX_BULK_BUSINESSES) {
    return actionFailure(t("changeImpact.error.tooMany", { max: MAX_BULK_BUSINESSES }));
  }
  const result = await changeImpactGateway({ session }).sendChangeCards(
    ruleVersionId.toLowerCase(),
    unique,
    idempotencyHeaders(formData, "notification.bulk"),
  );
  if (!result.ok) {
    if (isProblem(result.error, BULK_DISABLED)) {
      return {
        status: "error",
        problem: toActionProblem(result.error),
        formErrors: [t("changeImpact.error.disabled")],
      };
    }
    return toActionState<BulkSummary>({ ok: false, error: result.error });
  }
  const summary = bulkSummary(result.value.value, result.value.replayed);
  return actionSuccess(summary, summary.message);
}
