"use server";

import type { SessionClaims } from "@/entities/session/types";
import type {
  DraftEdit,
  DraftFields,
  ReviewTaskDetail,
  TaskDecision,
} from "@/entities/rule-version/types";
import { rulebookWrites } from "@/server/api/rulebook-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import type { ApiError } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  type ActionState,
  type FieldErrors,
} from "@/shared/lib/action-state";
import { formatDateTime } from "@/shared/lib/dates";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import { candidateStatusLabel } from "./model/candidate";
import { parseClaim, parseDecision, parseDraft, parseEdit, type Parsed } from "./model/forms";
import { decisionLabel, taskHref } from "./model/queue";
import { REVIEW_PROBLEMS, isRefusal, onRelationRows, refusalState } from "./model/refusals";
import { checkRelations } from "./model/workbench";
import { relationsOffered, taskNow } from "./queries";
import type { WriteResult } from "./ui/form-shared";

/**
 * The review steps: claim a task (from the queue or the workbench), open the seed tasks, draft a
 * version from a candidate, edit a draft, and decide. Each action runs the page's gate again (the
 * proxy is not on an action's path), checks the task id and the form's shape, and checks the role
 * the step needs (approving is a reviewer's or an admin's, D-061), then goes to the rulebook
 * through `server/api/rulebook-write.ts`, which checks the role, web.admin_rulebook_writes and the
 * review token and names the session's user as the actor. The rulebook owns the rules; its
 * refusals come back in plain words (model/refusals.ts). A step the rulebook says was taken
 * already (a task claimed by someone else, decided before the decision arrived) is read again and
 * said with who holds or decided it. On success the queue, the task and the stats render again.
 */
const QUEUE = screenById("admin.review");
const TASK = screenById("admin.review.task");
const STATS = screenById("admin.review.stats");

function refresh(taskId: string | null): void {
  afterMutation({
    paths: [
      hrefFor(QUEUE),
      hrefFor(STATS),
      ...(taskId === null ? [] : [hrefFor(TASK, { taskId })]),
    ],
  });
}

function who(userId: string | null, session: SessionClaims): string {
  if (userId === null) return t("workbench.someone");
  return userId === session.userId ? t("workbench.you") : userId;
}

function result(
  message: string,
  details: string[] = [],
  links: { href: string; label: string }[] = [],
  kind: WriteResult["kind"] = "done",
): WriteResult {
  return { kind, message, details, links };
}

function failure<T>(parsed: Extract<Parsed<unknown>, { ok: false }>): ActionState<T> {
  const fieldErrors: FieldErrors = parsed.errors;
  return Object.keys(fieldErrors).length === 0
    ? actionFailure(parsed.formErrors)
    : { status: "error", fieldErrors, formErrors: parsed.formErrors };
}

/** Who decided a task, read again: "Already decided: Approved by you on 1 Jan 2000, ...". */
function decidedResult(detail: ReviewTaskDetail, session: SessionClaims): WriteResult {
  const task = detail.task;
  return result(
    t("workbench.alreadyDecided", {
      decision: task.decision === null ? t("common.unknown") : decisionLabel(task.decision),
      who: who(task.decidedBy, session),
      when: task.decidedAt === null ? t("common.unknown") : formatDateTime(task.decidedAt),
    }),
    task.note === "" ? [] : [t("workbench.decisionNote", { note: task.note })],
    [],
    "already",
  );
}

/**
 * A refusal the rulebook gave because the task moved: decided before the request arrived (shown
 * as information), or claimed by someone else (shown as the refusal, naming who). Anything else,
 * or a read that fails, passes on in plain words.
 */
async function refusal<T>(
  error: ApiError,
  taskId: string,
  session: SessionClaims,
  done: (found: WriteResult) => T,
): Promise<ActionState<T>> {
  const closed = isRefusal(error, REVIEW_PROBLEMS.closed);
  const claimed =
    isRefusal(error, REVIEW_PROBLEMS.claimed) || isRefusal(error, REVIEW_PROBLEMS.notClaimed);
  if (closed || claimed || isRefusal(error, REVIEW_PROBLEMS.alreadyDrafted)) refresh(taskId);
  if (closed || claimed) {
    const now = await taskNow(taskId);
    if (now.ok && now.value !== null) {
      const task = now.value.task;
      if (closed && task.status === "decided") {
        const found = decidedResult(now.value, session);
        return actionSuccess(done(found), found.message);
      }
      if (claimed && task.claimedBy !== null && task.claimedBy !== session.userId) {
        const state = refusalState<T>(error);
        if (state.status !== "error") return state;
        return {
          ...state,
          problem: {
            ...(state.problem ?? { type: "", title: "" }),
            title: t("workbench.claimedBy", {
              who: who(task.claimedBy, session),
              when: task.claimedAt === null ? t("common.unknown") : formatDateTime(task.claimedAt),
            }),
          },
        };
      }
    }
  }
  return refusalState<T>(error);
}

function taskIdOk(taskId: string): boolean {
  return isHexUuid(taskId);
}

// ---- Claim --------------------------------------------------------------------------------------

async function claim(taskId: string, session: SessionClaims): Promise<ActionState<WriteResult>> {
  const writes = await rulebookWrites({ session });
  const claimed = await writes.claimTask(taskId);
  if (!claimed.ok) return refusal(claimed.error, taskId, session, (found) => found);
  refresh(taskId);
  const done = result(
    t("workbench.claimed"),
    [],
    [{ href: taskHref(taskId), label: t("workbench.openTask") }],
  );
  return actionSuccess(done, done.message);
}

/** The workbench's claim: the task the page shows, by the signed-in analyst. */
export async function claimTask(taskId: string): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASK, { taskId });
  if (!taskIdOk(taskId)) return actionFailure(t("workbench.error.task"));
  return claim(taskId.toLowerCase(), session);
}

/** A queue row's claim: the task the row names. */
export async function claimFromQueue(
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(QUEUE);
  const taskId = parseClaim(formData);
  if (taskId === null) return actionFailure(t("workbench.error.task"));
  return claim(taskId, session);
}

// ---- Seed tasks ---------------------------------------------------------------------------------

/** A task for every seed draft that needs review and has none waiting. */
export async function openSeedTasks(): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(QUEUE);
  const writes = await rulebookWrites({ session });
  const opened = await writes.openSeedTasks();
  if (!opened.ok) return refusalState(opened.error);
  refresh(null);
  const done = result(
    opened.value.opened === 0
      ? t("reviewQueue.seed.none")
      : t("reviewQueue.seed.opened", { count: opened.value.opened }),
  );
  return actionSuccess(done, done.message);
}

// ---- Draft and edit -----------------------------------------------------------------------------

const FIELD_WORDS: Readonly<Record<keyof DraftFields, () => string>> = {
  title: () => t("workbench.diff.field.title"),
  summary: () => t("workbench.diff.field.summary"),
  specification: () => t("workbench.diff.field.specification"),
  obligationTemplate: () => t("workbench.diff.field.template"),
  recurrence: () => t("workbench.diff.field.recurrence"),
  effectiveFrom: () => t("workbench.field.effectiveFrom"),
  effectiveTo: () => t("workbench.field.effectiveTo"),
  todo: () => t("workbench.diff.field.todo"),
};

function changedWords(fields: DraftFields): string {
  return (Object.keys(fields) as (keyof DraftFields)[])
    .map((field) => FIELD_WORDS[field]())
    .join(", ");
}

function savedResult(edit: DraftEdit): WriteResult {
  const details: string[] = [];
  if (Object.keys(edit.fields).length > 0) {
    details.push(t("workbench.edit.changed", { fields: changedWords(edit.fields) }));
  }
  if (edit.citations.length > 0) {
    details.push(t("workbench.edit.cited", { count: edit.citations.length }));
  }
  return result(t("workbench.edit.saved"), details);
}

/**
 * A version drafted from a claimed candidate task's candidate. The relation candidates it takes
 * on are checked against the ones the form offers, read again from the rulebook, before anything
 * is sent: a crafted request could otherwise attach a relation to any version (D-061).
 */
export async function draftFromCandidate(
  taskId: string,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASK, { taskId });
  if (!taskIdOk(taskId)) return actionFailure(t("workbench.error.task"));
  const parsed = parseDraft(formData);
  if (!parsed.ok) return failure(parsed);
  const id = taskId.toLowerCase();
  const relations = parsed.value.relations;
  if (relations.length > 0) {
    const offered = await relationsOffered(id);
    if (!offered.ok) return refusalState(offered.error);
    const problems = checkRelations(relations, offered.value);
    if (Object.keys(problems).length > 0) return { status: "error", fieldErrors: problems };
  }
  const writes = await rulebookWrites({ session });
  const drafted = await writes.draftFromCandidate(id, parsed.value);
  if (!drafted.ok) {
    return onRelationRows(await refusal(drafted.error, id, session, (found) => found), relations);
  }
  refresh(id);
  const version = drafted.value.version;
  const done = result(
    version === null
      ? t("workbench.draft.done")
      : t("workbench.draft.doneVersion", { rule: version.ruleKey, version: version.version }),
    [
      ...(parsed.value.relations.length === 0
        ? []
        : [t("workbench.draft.relations", { count: parsed.value.relations.length })]),
      t("workbench.draft.cited", { count: drafted.value.citations.length }),
    ],
  );
  return actionSuccess(done, done.message);
}

/** An edit of a claimed task's draft: the fields changed, the citations added and why. */
export async function editDraft(
  taskId: string,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASK, { taskId });
  if (!taskIdOk(taskId)) return actionFailure(t("workbench.error.task"));
  const parsed = parseEdit(formData);
  if (!parsed.ok) return failure(parsed);
  const id = taskId.toLowerCase();
  const writes = await rulebookWrites({ session });
  const edited = await writes.editDraft(id, parsed.value);
  if (!edited.ok) return refusal(edited.error, id, session, (found) => found);
  refresh(id);
  const done = savedResult(parsed.value);
  return actionSuccess(done, done.message);
}

// ---- Decide -------------------------------------------------------------------------------------

function decisionResult(decision: TaskDecision, session: SessionClaims): WriteResult {
  const { task, version } = decision;
  const details: string[] = [];
  const links: { href: string; label: string }[] = [];
  let message: string;
  if (task.decision === "approve") {
    message = t("workbench.decide.approved");
  } else if (task.decision === "return") {
    message = t("workbench.decide.returned");
  } else if (task.decision === "reject") {
    message = t("workbench.decide.rejected");
  } else {
    const count = version?.approvedBy.length ?? 0;
    message = t("workbench.decide.approvalRecorded", {
      count,
      required: version?.requiredApprovals ?? count,
    });
    details.push(t("workbench.decide.needsAnother"));
  }
  if (version !== null) {
    details.push(
      t("workbench.decide.versionStatus", { status: ruleVersionStatusLabel(version.status) }),
    );
    if (version.approvedBy.length > 0) {
      details.push(
        t("workbench.decide.approvers", {
          approvers: version.approvedBy.map((userId) => who(userId, session)).join(", "),
        }),
      );
    }
    if (version.status === "approved") {
      links.push({
        href: hrefFor(screenById("admin.rulebook.version"), {
          ruleVersionId: version.ruleVersionId,
        }),
        label: t("workbench.publishLink"),
      });
    }
  }
  if (decision.candidateStatus !== null) {
    details.push(
      t("workbench.decide.candidateStatus", {
        status: candidateStatusLabel(decision.candidateStatus),
      }),
    );
  }
  if (decision.nextTaskId !== null) {
    links.push({ href: taskHref(decision.nextTaskId), label: t("workbench.decide.nextTask") });
  }
  return result(message, details, links);
}

/**
 * Approve, return or reject. Approving is a reviewer's or an admin's (the rulebook's shared review
 * token would take it from any analyst, so the role is checked here, D-061); the same reviewer
 * approving a round twice is the rulebook's refusal, said as "a different reviewer must approve".
 */
export async function decideTask(
  taskId: string,
  candidateTask: boolean,
  _state: ActionState<WriteResult>,
  formData: FormData,
): Promise<ActionState<WriteResult>> {
  const session = await requireScreenSession(TASK, { taskId });
  if (!taskIdOk(taskId)) return actionFailure(t("workbench.error.task"));
  const parsed = parseDecision(formData, candidateTask);
  if (!parsed.ok) return failure(parsed);
  if (parsed.value.decision === "approve" && !can(session, "admin.review.approve")) {
    return actionFailure(t("workbench.decide.blockedRole"));
  }
  const id = taskId.toLowerCase();
  const writes = await rulebookWrites({ session });
  const decided = await writes.decideTask(id, parsed.value);
  if (!decided.ok) return refusal(decided.error, id, session, (found) => found);
  refresh(id);
  const done = decisionResult(decided.value, session);
  return actionSuccess(done, done.message);
}
