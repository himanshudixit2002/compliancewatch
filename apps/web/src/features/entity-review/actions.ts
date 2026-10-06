"use server";

import { isProblemOf } from "@/entities/problem/mappers";
import type { EntityType } from "@/entities/rulebook/types";
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
import { entityReviewGateway } from "./gateway";
import { parseDecision } from "./model/decision-form";
import { alreadyDecidedResult, canName, decisionResult, NAME_MAX_LENGTH } from "./model/group";
import { isEntityType } from "./model/queue";
import type { DecisionResult } from "./ui/decision-shared";

/**
 * Decides one review group: the page's gate again (the proxy is not on an action's path), the
 * group and the form's shape (a decision; the entity for add_alias; the reason for reject; a note
 * of at most 2000 characters; at most 200 mentions), then the rulebook through
 * `server/api/rulebook-write.ts`, which checks the role, web.admin_rulebook_writes for the
 * session's tenant and the review token, and names the session's user as `decided_by`. The
 * rulebook owns the rules (a name that is not canonical, an entity of another type): its refusal
 * comes back with its problem, except mentions already decided, which are shown as information
 * once the group is read again. On success the queue and the group render again, the decided
 * mentions gone.
 */
const QUEUE = screenById("admin.rulebook.entities");
const GROUP = screenById("admin.rulebook.entities.group");

/** The rulebook's refusal of a decision whose mentions are no longer open. */
const GROUP_CLOSED = "rulebook-review-group-closed";

/**
 * What a refused decision shows. The decision route takes no Idempotency-Key, so a decision sent
 * again after its answer was lost comes back as 409 "already decided" although it was recorded.
 * The group is read again: when none of the included mentions is open any more (or, for the whole
 * group, the read succeeds), the page renders again with what is open now and the panel says the
 * mentions were already decided, as information. Any other refusal, or a read that fails or still
 * finds an included mention open, is shown as the rulebook's problem.
 */
async function refusal(
  error: ApiError,
  entityType: EntityType,
  proposedName: string,
  reviewIds: readonly string[] | undefined,
): Promise<ActionState<DecisionResult>> {
  if (error.status === 409 && isProblemOf(error.problem, GROUP_CLOSED)) {
    const items = await entityReviewGateway().items(entityType, proposedName);
    if (items.ok) {
      const open = new Set(items.value.map((item) => item.reviewId.toLowerCase()));
      if (reviewIds === undefined || !reviewIds.some((id) => open.has(id))) {
        afterMutation({ paths: [hrefFor(QUEUE), hrefFor(GROUP)] });
        const already = alreadyDecidedResult(reviewIds !== undefined);
        return actionSuccess(already, already.message);
      }
    }
  }
  return toActionState<DecisionResult>({ ok: false, error });
}

export async function decideEntityGroup(
  entityType: string,
  proposedName: string,
  _state: ActionState<DecisionResult>,
  formData: FormData,
): Promise<ActionState<DecisionResult>> {
  const session = await requireScreenSession(GROUP);
  if (!isEntityType(entityType) || proposedName.length > NAME_MAX_LENGTH) {
    return actionFailure(t("entityReview.error.group"));
  }
  const parsed = parseDecision(formData, canName(entityType, proposedName));
  if (!parsed.ok) return fieldFailure(parsed.errors);
  const writes = await rulebookWrites({ session });
  const result = await writes.decideEntityGroup({
    entityType: entityType as EntityType,
    proposedName,
    decision: parsed.decision,
    ...(parsed.entityId === undefined ? {} : { entityId: parsed.entityId }),
    ...(parsed.rejectReason === undefined ? {} : { rejectReason: parsed.rejectReason }),
    ...(parsed.reviewIds === undefined ? {} : { reviewIds: parsed.reviewIds }),
    note: parsed.note,
  });
  if (!result.ok) {
    return refusal(result.error, entityType as EntityType, proposedName, parsed.reviewIds);
  }
  afterMutation({ paths: [hrefFor(QUEUE), hrefFor(GROUP)] });
  const done = decisionResult(result.value);
  return actionSuccess(done, done.message);
}
