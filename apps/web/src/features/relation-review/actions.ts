"use server";

import { rulebookWrites } from "@/server/api/rulebook-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import { approvedResult, rejectedResult } from "./model/candidate";
import { parseApproval, parseRejection } from "./model/decision-form";
import { candidateRejectReasonLabel, type CandidateDecisionResult } from "./ui/decision-shared";

/**
 * Approves or rejects one relation candidate: the page's gate again (the proxy is not on an
 * action's path), the candidate's id and the form's shape, then the rulebook through
 * `server/api/rulebook-write.ts`, which checks the role, web.admin_rulebook_writes for the
 * session's tenant and the review token, and names the session's user as `decided_by`. The
 * rulebook owns the rules (the version a relation starts from must be an open draft, the target
 * must be aligned or a version named, no supersession cycle): its refusal comes back with its
 * problem. On success the queue and the candidate render again in the new status.
 */
const QUEUE = screenById("admin.rulebook.relations");
const PAGE = screenById("admin.rulebook.relation");

function refresh(candidateId: string): void {
  afterMutation({ paths: [hrefFor(QUEUE), hrefFor(PAGE, { candidateId })] });
}

export async function approveCandidate(
  candidateId: string,
  needsTarget: boolean,
  _state: ActionState<CandidateDecisionResult>,
  formData: FormData,
): Promise<ActionState<CandidateDecisionResult>> {
  const session = await requireScreenSession(PAGE, { candidateId });
  if (!isHexUuid(candidateId)) return actionFailure(t("relationReview.error.candidate"));
  const parsed = parseApproval(formData, needsTarget);
  if (!parsed.ok) return fieldFailure(parsed.errors);
  const writes = await rulebookWrites({ session });
  const result = await writes.approveCandidate(candidateId.toLowerCase(), parsed.approval);
  if (!result.ok) return toActionState<CandidateDecisionResult>({ ok: false, error: result.error });
  refresh(candidateId);
  const done = approvedResult(result.value.ruleRelationId, parsed.approval.fromRuleVersionId);
  return actionSuccess(done, done.message);
}

export async function rejectCandidate(
  candidateId: string,
  _state: ActionState<CandidateDecisionResult>,
  formData: FormData,
): Promise<ActionState<CandidateDecisionResult>> {
  const session = await requireScreenSession(PAGE, { candidateId });
  if (!isHexUuid(candidateId)) return actionFailure(t("relationReview.error.candidate"));
  const parsed = parseRejection(formData);
  if (!parsed.ok) return fieldFailure(parsed.errors);
  const writes = await rulebookWrites({ session });
  const result = await writes.rejectCandidate(candidateId.toLowerCase(), parsed.rejection);
  if (!result.ok) return toActionState<CandidateDecisionResult>({ ok: false, error: result.error });
  refresh(candidateId);
  const done = rejectedResult(candidateRejectReasonLabel(parsed.rejection.reason));
  return actionSuccess(done, done.message);
}
