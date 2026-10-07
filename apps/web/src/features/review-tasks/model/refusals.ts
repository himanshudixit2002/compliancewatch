import { isProblemOf, problemSlug } from "@/entities/problem/mappers";
import { toActionProblem, type ApiError } from "@/server/result";
import { t, type MessageKey } from "@/shared/i18n";
import type { ActionState } from "@/shared/lib/action-state";
import { relationField } from "../ui/form-shared";

/**
 * The rulebook's refusals of a review step, said plainly. Each keeps the rulebook's problem type,
 * its detail where the words here do not replace it, and the correlation id to quote; a refusal
 * not listed passes on as the rulebook worded it. A refusal that names a person (a task claimed by
 * someone else) or a state (a task decided before the decision arrived) is read again by the
 * action and worded there.
 */
export const REVIEW_PROBLEMS = {
  claimed: "rulebook-review-task-claimed",
  notClaimed: "rulebook-review-task-not-claimed",
  closed: "rulebook-review-task-closed",
  alreadyDrafted: "rulebook-candidate-already-drafted",
  draftIncomplete: "rulebook-draft-incomplete",
  duplicateApprover: "rulebook-duplicate-approver",
} as const;

interface Words {
  title: MessageKey;
  /** Replaces the rulebook's detail; absent keeps it. */
  detail?: MessageKey;
}

const WORDS: Readonly<Record<string, Words>> = {
  "rulebook-review-task-not-claimed": { title: "workbench.refusal.notClaimed" },
  "rulebook-rule-key-unknown": {
    title: "workbench.refusal.ruleKeyUnknown",
    detail: "workbench.refusal.ruleKeyUnknownDetail",
  },
  "rulebook-rule-key-taken": {
    title: "workbench.refusal.ruleKeyTaken",
    detail: "workbench.refusal.ruleKeyTakenDetail",
  },
  "rulebook-candidate-already-drafted": {
    title: "workbench.refusal.alreadyDrafted",
    detail: "workbench.refusal.alreadyDraftedDetail",
  },
  "rulebook-candidate-not-drafted": {
    title: "workbench.refusal.notDrafted",
    detail: "workbench.refusal.notDraftedDetail",
  },
  "rulebook-overlapping-version": { title: "workbench.refusal.overlapping" },
  "rulebook-citation-not-verified": { title: "workbench.refusal.citationNotVerified" },
  "rulebook-clause-unknown": { title: "workbench.refusal.clauseUnknown" },
  "rulebook-clause-not-found": { title: "workbench.refusal.clauseNotFound" },
  "rulebook-rule-version-closed": {
    title: "workbench.refusal.closed",
    detail: "workbench.refusal.closedDetail",
  },
  "rulebook-rule-version-not-editable": {
    title: "workbench.refusal.notEditable",
    detail: "workbench.refusal.notEditableDetail",
  },
  "rulebook-draft-incomplete": {
    title: "workbench.refusal.incomplete",
    detail: "workbench.refusal.incompleteDetail",
  },
  "rulebook-approvals-missing": { title: "workbench.refusal.approvalsMissing" },
  "rulebook-citations-missing": {
    title: "workbench.refusal.citationsMissing",
    detail: "workbench.refusal.citationsMissingDetail",
  },
  "rulebook-synthetic-approval-refused": { title: "workbench.refusal.synthetic" },
  "rulebook-duplicate-approver": {
    title: "workbench.refusal.duplicateApprover",
    detail: "workbench.refusal.duplicateApproverDetail",
  },
  "rulebook-target-version-required": { title: "workbench.refusal.targetVersionRequired" },
  "rulebook-reviews-disabled": {
    title: "workbench.refusal.reviewsDisabled",
    detail: "workbench.refusal.reviewsDisabledDetail",
  },
  "rulebook-review-token-invalid": {
    title: "workbench.refusal.tokenInvalid",
    detail: "workbench.refusal.tokenInvalidDetail",
  },
};

/** The problems a draft-incomplete or an invariant refusal lists, one per line of its detail. */
export function listedProblems(error: ApiError): string[] {
  const detail = error.problem?.detail ?? "";
  if (!isProblemOf(error.problem, REVIEW_PROBLEMS.draftIncomplete)) return [];
  return detail
    .split("; ")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** The refusal as the form shows it: plain words, the rulebook's problem type and the id. */
export function refusalState<T>(error: ApiError): ActionState<T> {
  const problem = toActionProblem(error);
  const slug = problemSlug(error.problem);
  const words = slug === null ? undefined : WORDS[slug];
  const listed = listedProblems(error);
  const fieldErrors = error.fieldErrors;
  return {
    status: "error",
    problem:
      words === undefined
        ? problem
        : {
            ...problem,
            title: t(words.title),
            ...(words.detail === undefined ? {} : { detail: t(words.detail) }),
          },
    ...(listed.length === 0 ? {} : { formErrors: listed }),
    ...(fieldErrors !== undefined && Object.keys(fieldErrors).length > 0 ? { fieldErrors } : {}),
  };
}

/** A rulebook field under the relation list: `relation_candidates.<n>.<field>`. */
const RELATION_LIST_FIELD = /^relation_candidates\.(\d+)\.(.+)$/;

/**
 * A refusal's field errors on the relation list moved onto the form's rows: the rulebook names a
 * relation by its place in the list sent (`relation_candidates.<n>.target_rule_version_id`), the
 * form names its rows by candidate id (`relation.<id>.target`). Any other field stays as it is.
 */
export function onRelationRows<T>(
  state: ActionState<T>,
  sent: readonly { candidateId: string }[],
): ActionState<T> {
  if (state.status !== "error" || state.fieldErrors === undefined) return state;
  const fieldErrors: Record<string, readonly string[]> = {};
  for (const [field, messages] of Object.entries(state.fieldErrors)) {
    const match = RELATION_LIST_FIELD.exec(field);
    const relation = match === null ? undefined : sent[Number(match[1])];
    const key =
      relation === undefined
        ? field
        : relationField(
            relation.candidateId,
            (match?.[2] ?? "").startsWith("target") ? "target" : "take",
          );
    fieldErrors[key] = [...(fieldErrors[key] ?? []), ...messages];
  }
  return { ...state, fieldErrors };
}

/** Whether the refusal is this one of the rulebook's. */
export function isRefusal(error: ApiError, slug: string): boolean {
  return error.problem !== undefined && isProblemOf(error.problem, slug);
}
