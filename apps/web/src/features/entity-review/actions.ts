"use server";

import type { EntityType } from "@/entities/rulebook/types";
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
import { parseDecision } from "./model/decision-form";
import { canName, decisionResult, NAME_MAX_LENGTH } from "./model/group";
import { isEntityType } from "./model/queue";
import type { DecisionResult } from "./ui/decision-shared";

/**
 * Decides one review group: the page's gate again (the proxy is not on an action's path), the
 * group and the form's shape (a decision; the entity for add_alias; the reason for reject; a note
 * of at most 2000 characters; at most 200 mentions), then the rulebook through
 * `server/api/rulebook-write.ts`, which checks the role, web.admin_rulebook_writes for the
 * session's tenant and the review token, and names the session's user as `decided_by`. The
 * rulebook owns the rules (a name that is not canonical, a closed group, an entity of another
 * type): its refusal comes back with its problem. On success the queue and the group render
 * again, the decided mentions gone.
 */
const QUEUE = screenById("admin.rulebook.entities");
const GROUP = screenById("admin.rulebook.entities.group");

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
  if (!result.ok) return toActionState<DecisionResult>({ ok: false, error: result.error });
  afterMutation({ paths: [hrefFor(QUEUE), hrefFor(GROUP)] });
  const done = decisionResult(result.value);
  return actionSuccess(done, done.message);
}
