"use server";

import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { screenById } from "@/shared/config/screens";
import { fieldFailure, actionSuccess } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";
import { rulebookWrites } from "@/server/api/rulebook-write";
import type { CandidateApproval, CandidateRejection, EntityGroupDecision, EntityRejectReason, EntityType, MentionDecision } from "@/entities/rulebook/types";

const REVIEW_SCREEN = screenById("admin.review");

interface EntityFormResult {
  entityType: string;
  proposedName: string;
  decision: string;
  rejectReason: string;
  entityId?: string;
  note: string;
}

function parseEntityForm(formData: FormData): EntityFormResult {
  return {
    entityType: String(formData.get("entityType") ?? ""),
    proposedName: String(formData.get("proposedName") ?? ""),
    decision: String(formData.get("decision") ?? "create_entity"),
    rejectReason: String(formData.get("rejectReason") ?? "not_an_entity"),
    note: String(formData.get("note") ?? ""),
  };
}

interface RelationFormResult {
  candidateId: string;
  action: string;
  rejectReason: string;
  fromRuleVersionId: string;
  targetRuleVersionId: string;
  note: string;
}

function parseRelationForm(formData: FormData): RelationFormResult {
  return {
    candidateId: String(formData.get("candidateId") ?? ""),
    action: String(formData.get("action") ?? "approve"),
    rejectReason: String(formData.get("rejectReason") ?? "wrong_kind"),
    fromRuleVersionId: String(formData.get("fromRuleVersionId") ?? ""),
    targetRuleVersionId: String(formData.get("targetRuleVersionId") ?? ""),
    note: String(formData.get("note") ?? ""),
  };
}

const VALID_DECISIONS = new Set(["create_entity", "add_alias", "reject"]);
const VALID_ACTIONS = new Set(["approve", "reject"]);

export async function decideEntityGroup(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const session = await requireScreenSession(REVIEW_SCREEN);
  const { entityType, proposedName, decision, rejectReason, note } = parseEntityForm(formData);

  if (!VALID_DECISIONS.has(decision)) {
    return fieldFailure({ form: ["Choose a valid decision."] });
  }

  const dto: EntityGroupDecision = {
    entityType: entityType as EntityType,
    proposedName,
    decision: decision as MentionDecision,
    entityId: undefined,
    rejectReason: rejectReason as EntityRejectReason | undefined,
    note,
    ...(decision === "reject" && rejectReason !== ""
      ? { rejectReason: rejectReason as EntityGroupDecision["rejectReason"] }
      : {}),
  };

  const writes = await rulebookWrites({ session: session as never });
  const result = await writes.decideEntityGroup(dto);
  if (!result.ok) return toActionState(result);

  return actionSuccess(undefined, "Decision recorded.");
}

export async function decideCandidate(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const session = await requireScreenSession(REVIEW_SCREEN);
  const { candidateId, action, rejectReason, fromRuleVersionId, targetRuleVersionId, note } =
    parseRelationForm(formData);

  if (!VALID_ACTIONS.has(action)) {
    return fieldFailure({ form: ["Choose approve or reject."] });
  }

  const writes = await rulebookWrites({ session: session as never });

  if (action === "approve") {
    if (fromRuleVersionId === "") {
      return fieldFailure({ form: ["A rule version id is required for approval."] });
    }
    const approval: CandidateApproval = {
      fromRuleVersionId,
      note,
      ...(targetRuleVersionId !== "" ? { targetRuleVersionId } : {}),
    };
    const result = await writes.approveCandidate(candidateId, approval);
    if (!result.ok) return toActionState(result);
    return actionSuccess(undefined, "Candidate approved.");
  }

  const result = await writes.rejectCandidate(candidateId, {
    reason: rejectReason as CandidateRejection["reason"],
    note,
  });
  if (!result.ok) return toActionState(result);

  return actionSuccess(undefined, "Candidate rejected.");
}