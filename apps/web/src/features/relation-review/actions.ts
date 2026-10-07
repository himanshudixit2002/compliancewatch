"use server";

import { isProblemOf } from "@/entities/problem/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { rulebookWrites } from "@/server/api/rulebook-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState, type ApiError } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import { relationReviewGateway } from "./gateway";
import {
  alreadyDecidedResult,
  approvedResult,
  needsTargetVersion,
  rejectedResult,
} from "./model/candidate";
import { parseApproval, parseRejection, unofferedVersions } from "./model/decision-form";
import { approvalOptions, findCandidate } from "./queries";
import { candidateRejectReasonLabel, type CandidateDecisionResult } from "./ui/decision-shared";

/**
 * Approves or rejects one relation candidate: the page's gate again (the proxy is not on an
 * action's path), the candidate's id and the form's shape, then the rulebook through
 * `server/api/rulebook-write.ts`, which checks the role, web.admin_rulebook_writes for the
 * session's tenant and the review token, and names the session's user as `decided_by`. The
 * rulebook owns the rules (the version a relation starts from must be an open draft, the target
 * must be aligned or a version named, no supersession cycle): its refusal comes back with its
 * problem, except a candidate already decided, which is read again and shown as information. On
 * success the queue and the candidate render again in the new status.
 */
const QUEUE = screenById("admin.rulebook.relations");
const PAGE = screenById("admin.rulebook.relation");

function refresh(candidateId: string): void {
  afterMutation({ paths: [hrefFor(QUEUE), hrefFor(PAGE, { candidateId })] });
}

/** The rulebook's refusal of a decision over a candidate that is no longer open. */
const CANDIDATE_CLOSED = "rulebook-relation-candidate-closed";

/**
 * What a refused decision shows. The routes take no Idempotency-Key, so a decision sent again
 * after its answer was lost comes back as 409 "already decided" although it was recorded: the
 * candidate is read again and its decided state (who decided, and how) is shown as information,
 * and the page renders again in that state. Any other refusal, or a read that fails or finds the
 * candidate still open, is shown as the rulebook's problem.
 */
async function refusal(
  error: ApiError,
  candidateId: string,
  sent: "approved" | "rejected",
  session: SessionClaims,
): Promise<ActionState<CandidateDecisionResult>> {
  if (error.status === 409 && isProblemOf(error.problem, CANDIDATE_CLOSED)) {
    const found = await findCandidate(relationReviewGateway(), candidateId, sent);
    if (found.ok && found.value !== null && found.value.status !== "open") {
      refresh(candidateId);
      const already = alreadyDecidedResult(found.value, session.userId);
      return actionSuccess(already, already.message);
    }
  }
  return toActionState<CandidateDecisionResult>({ ok: false, error });
}

/**
 * Approves a candidate. The form's shape is checked first; then the candidate and the versions the
 * page offers it are read again, so whether it needs a target comes from the rulebook rather than
 * the page, and a version the page did not offer is refused before anything is sent (D-061). A
 * candidate decided meanwhile is said as information, as the rulebook's refusal of it would be.
 */
export async function approveCandidate(
  candidateId: string,
  _state: ActionState<CandidateDecisionResult>,
  formData: FormData,
): Promise<ActionState<CandidateDecisionResult>> {
  const session = await requireScreenSession(PAGE, { candidateId });
  if (!isHexUuid(candidateId)) return actionFailure(t("relationReview.error.candidate"));
  const shape = parseApproval(formData, false);
  if (!shape.ok) return fieldFailure(shape.errors);
  const id = candidateId.toLowerCase();
  const offered = await approvalOptions(id);
  if (!offered.ok)
    return toActionState<CandidateDecisionResult>({ ok: false, error: offered.error });
  if (offered.value === null) return actionFailure(t("relationReview.error.gone"));
  const { candidate, options } = offered.value;
  if (candidate.status !== "open") {
    refresh(candidateId);
    const already = alreadyDecidedResult(candidate, session.userId);
    return actionSuccess(already, already.message);
  }
  const parsed = parseApproval(formData, needsTargetVersion(candidate));
  if (!parsed.ok) return fieldFailure(parsed.errors);
  const unoffered = unofferedVersions(parsed.approval, options);
  if (Object.keys(unoffered).length > 0) return fieldFailure(unoffered);
  const writes = await rulebookWrites({ session });
  const result = await writes.approveCandidate(id, parsed.approval);
  if (!result.ok) return refusal(result.error, id, "approved", session);
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
  const id = candidateId.toLowerCase();
  const writes = await rulebookWrites({ session });
  const result = await writes.rejectCandidate(id, parsed.rejection);
  if (!result.ok) return refusal(result.error, id, "rejected", session);
  refresh(candidateId);
  const done = rejectedResult(candidateRejectReasonLabel(parsed.rejection.reason));
  return actionSuccess(done, done.message);
}
