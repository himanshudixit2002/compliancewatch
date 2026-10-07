import { isProblemOf, problemSlug } from "@/entities/problem/mappers";
import { toActionProblem, type ApiError } from "@/server/result";
import { t, type MessageKey } from "@/shared/i18n";
import type { ActionState } from "@/shared/lib/action-state";
import { relationField } from "../ui/form-shared";

/**
 * The rulebook's refusals of a review step, said plainly. Each keeps the rulebook's problem type,
 * its detail where the words here do not replace it, and the correlation id to quote; a refusal
 * not listed passes on as the rulebook worded it. A refusal that names a person (a task claimed by
 * someone else) or a state (a task decided before the step arrived) is read again by the action
 * and worded there. The kernel's `invariant-violation` carries the rulebook's own sentence: the
 * ones a form can meet (a draft into another regulator's rule, the rules of a decision) get their
 * own words, and any other is said for the step, with each problem it lists on a line of its own
 * (an edit's content problems, joined by "; ", as an incomplete draft's are). A refusal about a
 * relation candidate is put on the row it names where the detail lets it be found.
 */
export const REVIEW_PROBLEMS = {
  claimed: "rulebook-review-task-claimed",
  notClaimed: "rulebook-review-task-not-claimed",
  closed: "rulebook-review-task-closed",
  alreadyDrafted: "rulebook-candidate-already-drafted",
  draftIncomplete: "rulebook-draft-incomplete",
  duplicateApprover: "rulebook-duplicate-approver",
  invariant: "invariant-violation",
} as const;

/** The step a refusal answered, for the words of a refusal the rulebook gives every step. */
export type ReviewStep = "claim" | "seed" | "draft" | "edit" | "decide";

/** A relation candidate a draft sent, with what the rulebook's refusals may name it by. */
export interface SentRelation {
  candidateId: string;
  targetRuleVersionId: string | null;
  relation?: string;
  targetName?: string;
}

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
  "rulebook-relation-candidate-not-found": {
    title: "workbench.refusal.relationNotFound",
    detail: "workbench.refusal.relationNotFoundDetail",
  },
  "rulebook-relation-candidate-closed": {
    title: "workbench.refusal.relationClosed",
    detail: "workbench.refusal.relationClosedDetail",
  },
  "rulebook-relation-target-unresolved": {
    title: "workbench.refusal.targetUnresolved",
    detail: "workbench.refusal.targetUnresolvedDetail",
  },
  "rulebook-supersession-cycle": { title: "workbench.refusal.supersessionCycle" },
  "rulebook-rule-version-not-found": { title: "workbench.refusal.versionNotFound" },
  "rulebook-reviews-disabled": {
    title: "workbench.refusal.reviewsDisabled",
    detail: "workbench.refusal.reviewsDisabledDetail",
  },
  "rulebook-review-token-invalid": {
    title: "workbench.refusal.tokenInvalid",
    detail: "workbench.refusal.tokenInvalidDetail",
  },
};

/**
 * The `invariant-violation` sentences of the review routes a form can meet, by the words the
 * rulebook uses (rulebook.application.review_tasks); a sentence it rewords falls back to the
 * step's words with its own text below.
 */
const INVARIANT_WORDS: readonly { pattern: RegExp; words: Words }[] = [
  {
    pattern: /a rule of its own regulator/,
    words: {
      title: "workbench.refusal.regulatorMismatch",
      detail: "workbench.refusal.regulatorMismatchDetail",
    },
  },
  {
    pattern: /says why in its note/,
    words: { title: "workbench.refusal.noteRequired", detail: "workbench.refusal.nothingRecorded" },
  },
  {
    pattern: /high_impact is raised with an approval/,
    words: {
      title: "workbench.refusal.highImpactWithApproval",
      detail: "workbench.refusal.nothingRecorded",
    },
  },
  {
    pattern: /rejection names its reason/,
    words: {
      title: "workbench.refusal.reasonRequired",
      detail: "workbench.refusal.nothingRecorded",
    },
  },
  {
    pattern: /reason is given with a rejection|rejection takes a reason/,
    words: {
      title: "workbench.refusal.reasonOnlyCandidate",
      detail: "workbench.refusal.nothingRecorded",
    },
  },
  {
    pattern: /a relation candidate is picked once/,
    words: { title: "workbench.refusal.relationTwice", detail: "workbench.refusal.nothingStored" },
  },
  {
    pattern: /is about another document/,
    words: { title: "workbench.refusal.relationOtherDocument" },
  },
];

const INVARIANT_BY_STEP: Readonly<Record<ReviewStep, Words>> = {
  edit: {
    title: "workbench.refusal.contentRefused",
    detail: "workbench.refusal.contentRefusedDetail",
  },
  draft: { title: "workbench.refusal.draftRefused", detail: "workbench.refusal.listedDetail" },
  decide: {
    title: "workbench.refusal.decisionRefused",
    detail: "workbench.refusal.decisionRefusedDetail",
  },
  claim: { title: "workbench.refusal.requestRefused", detail: "workbench.refusal.listedDetail" },
  seed: { title: "workbench.refusal.requestRefused", detail: "workbench.refusal.listedDetail" },
};

/** The problems a draft-incomplete or an invariant refusal lists, one per line of its detail. */
export function listedProblems(error: ApiError): string[] {
  const detail = error.problem?.detail ?? "";
  if (
    !isProblemOf(error.problem, REVIEW_PROBLEMS.draftIncomplete) &&
    !isProblemOf(error.problem, REVIEW_PROBLEMS.invariant)
  ) {
    return [];
  }
  return detail
    .split("; ")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** The words for an invariant refusal: its own when the rulebook's sentence is known. */
function invariantWords(detail: string, step: ReviewStep): { words: Words; listed: boolean } {
  const known = INVARIANT_WORDS.find((entry) => entry.pattern.test(detail));
  return known === undefined
    ? { words: INVARIANT_BY_STEP[step], listed: true }
    : { words: known.words, listed: false };
}

/** The ids a detail names, lower-cased, in order. */
function idsIn(detail: string): string[] {
  return [
    ...detail.matchAll(
      /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g,
    ),
  ].map((match) => match[0].toLowerCase());
}

/**
 * A relation refusal on the row it is about, where its detail names the row: a candidate gone or
 * decided (by its id), a version the rulebook does not hold or a supersession that would close a
 * cycle (by the target's id), a target not aligned (by its name), a relation that needs a target
 * (by its kind, on a row sent without one).
 */
export function relationRowErrors(
  error: ApiError,
  sent: readonly SentRelation[],
): Record<string, string[]> {
  const detail = error.problem?.detail ?? "";
  const ids = idsIn(detail);
  const rows: Record<string, string[]> = {};
  const put = (relation: SentRelation, part: "take" | "target", message: string) => {
    rows[relationField(relation.candidateId, part)] = [message];
  };
  const slug = problemSlug(error.problem);
  for (const relation of sent) {
    switch (slug) {
      case "rulebook-relation-candidate-not-found":
      case "rulebook-relation-candidate-closed":
        if (ids.includes(relation.candidateId))
          put(relation, "take", t("workbench.error.relationNotOffered"));
        break;
      case "rulebook-rule-version-not-found":
        if (relation.targetRuleVersionId !== null && ids.includes(relation.targetRuleVersionId)) {
          put(relation, "target", t("workbench.error.relationTargetGone"));
        }
        break;
      case "rulebook-supersession-cycle":
        if (relation.targetRuleVersionId !== null && ids.at(-1) === relation.targetRuleVersionId) {
          put(relation, "target", t("workbench.error.relationCycle"));
        }
        break;
      case "rulebook-relation-target-unresolved":
        if (
          relation.targetRuleVersionId === null &&
          relation.targetName !== undefined &&
          relation.targetName !== "" &&
          detail.includes(`'${relation.targetName}'`)
        ) {
          put(relation, "target", t("workbench.error.relationUnaligned"));
        }
        break;
      case "rulebook-target-version-required":
        if (
          relation.targetRuleVersionId === null &&
          relation.relation !== undefined &&
          detail.startsWith(`${relation.relation} `)
        ) {
          put(relation, "target", t("workbench.error.relationTarget"));
        }
        break;
      default:
        break;
    }
  }
  return rows;
}

/**
 * The refusal as the form shows it: plain words, the rulebook's problem type and the id, each
 * problem it lists on a line, and a relation refusal on the row it names.
 */
export function refusalState<T>(
  error: ApiError,
  context: { step?: ReviewStep; relations?: readonly SentRelation[] } = {},
): ActionState<T> {
  const problem = toActionProblem(error);
  const slug = problemSlug(error.problem);
  let words = slug === null ? undefined : WORDS[slug];
  let listed = listedProblems(error);
  if (slug === REVIEW_PROBLEMS.invariant) {
    const invariant = invariantWords(error.problem?.detail ?? "", context.step ?? "claim");
    words = invariant.words;
    if (!invariant.listed) listed = [];
  }
  const rows = relationRowErrors(error, context.relations ?? []);
  const fieldErrors = { ...(error.fieldErrors ?? {}), ...rows };
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
    ...(Object.keys(fieldErrors).length > 0 ? { fieldErrors } : {}),
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
