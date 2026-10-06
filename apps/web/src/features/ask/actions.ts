"use server";

import type { RulebookDocument } from "@/entities/rulebook/types";
import { requireScreenSession } from "@/server/dal";
import { isEnabled } from "@/server/flags";
import { toActionState } from "@/server/result";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";
import { askGateway } from "./gateway";
import { answerView, checkQuestion, nodeOptions } from "./model/ask";
import { QA_FLAG } from "./queries";
import { ASK_FIELDS, type AnswerView } from "./ui/answer-shared";

/**
 * Asks the public API a question about one node of the business: the screen's gate again, the
 * flag for the session's tenant, the form's shape (the question travels in the POST body, never
 * an address), the node checked against the business, then `POST /v1/qa` and the cited documents
 * for their clauses' text. A refusal (the node unknown to the tenant, the model budget used up, a
 * service down) comes back as the service's problem with its correlation id.
 */
function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export async function askQuestion(
  _state: ActionState<AnswerView>,
  formData: FormData,
): Promise<ActionState<AnswerView>> {
  const businessId = text(formData, ASK_FIELDS.businessId);
  const session = await requireScreenSession(screenById("owner.ask"), { businessId });
  if (!(await isEnabled(QA_FLAG, { tenantId: session.tenantId }))) {
    return actionFailure(t("ask.off.refused"));
  }
  if (!isUuid(businessId)) return actionFailure(t("ask.badBusiness"));
  const gateway = askGateway({ session });
  const business = await gateway.business(businessId);
  if (!business.ok) return toActionState(business);
  const options = nodeOptions(business.value);
  const checked = checkQuestion(
    text(formData, ASK_FIELDS.question),
    text(formData, ASK_FIELDS.node),
    options,
    { question: ASK_FIELDS.question, node: ASK_FIELDS.node },
  );
  if (!checked.ok) return fieldFailure(checked.fieldErrors);
  const answer = await gateway.ask({ text: checked.question, nodeId: checked.nodeId });
  if (!answer.ok) return toActionState(answer);
  const ids = [...new Set(answer.value.citations.map((citation) => citation.documentId))];
  const documents = new Map<string, RulebookDocument>();
  for (const document of await Promise.all(ids.map((id) => gateway.document(id)))) {
    if (document.ok) documents.set(document.value.documentId, document.value);
  }
  const about = options.find((option) => option.id === checked.nodeId)?.label ?? checked.nodeId;
  return actionSuccess(answerView(answer.value, { question: checked.question, about, documents }));
}
