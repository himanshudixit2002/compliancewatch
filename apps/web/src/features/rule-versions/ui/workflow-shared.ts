import type { Publication, VersionLifecycle, WorkflowStep } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * What the workflow panel (a client component) shares with the server side of the feature: the
 * form's field names and limits, the shape of a step's answer, and the wording of a step and of
 * its outcome. It lives beside the panel because a client component imports only its own
 * directory, shared and entities; the model and the action import it from here.
 */
export const STEP_FIELDS = { step: "step", note: "note", highImpact: "high_impact" } as const;

/** The rulebook keeps a note of up to 2000 characters with each step. */
export const NOTE_MAX_LENGTH = 2000;

/** The steps that record a reason, which the rulebook keeps as the step's note. */
export const REASON_STEPS: ReadonlySet<WorkflowStep> = new Set(["return", "withdraw"]);

/** Whether the page may send citations and steps, and if not, the refusal to show. */
export type AccessView =
  { allowed: true } | { allowed: false; title: string; detail?: string; flag: string };

/** What a step answered, as the panel shows it; plain data, so it crosses to the browser. */
export interface StepResult {
  step: WorkflowStep;
  lifecycle: VersionLifecycle;
  /** Set for a publication: the versions it replaces and the due dates it moved. */
  publication: Pick<
    Publication,
    "correlationId" | "replacements" | "deadlineChanges" | "attributeKeys"
  > | null;
}

const STEP_LABELS: Readonly<Record<WorkflowStep, MessageKey>> = {
  submit: "ruleVersion.step.submit",
  approve: "ruleVersion.step.approve",
  publish: "ruleVersion.step.publish",
  return: "ruleVersion.step.return",
  withdraw: "ruleVersion.step.withdraw",
};

const DESCRIPTIONS: Readonly<Record<WorkflowStep, MessageKey>> = {
  submit: "ruleVersion.dialog.submit",
  approve: "ruleVersion.dialog.approve",
  publish: "ruleVersion.dialog.publish",
  return: "ruleVersion.dialog.return",
  withdraw: "ruleVersion.dialog.withdraw",
};

export function stepLabel(step: WorkflowStep): string {
  return t(STEP_LABELS[step]);
}

/** What the step's dialog says the rulebook records. */
export function stepDescription(step: WorkflowStep): string {
  return t(DESCRIPTIONS[step]);
}

export interface Approver {
  userId: string;
  /** The signed-in analyst. */
  you: boolean;
}

export interface RoundSummary {
  approvers: readonly Approver[];
  count: number;
  required: number;
  /** In review with some approvals but fewer than the round needs (one of two). */
  waitingForAnother: boolean;
}

/** The statuses that have a review round to report on: a draft has none until it is submitted. */
const ROUND_STATUSES: ReadonlySet<string> = new Set(["in_review", "approved", "published"]);

export function hasRound(lifecycle: VersionLifecycle): boolean {
  return ROUND_STATUSES.has(lifecycle.status);
}

/** The approvals of the round the last step reported, with the session's own marked. */
export function roundSummary(lifecycle: VersionLifecycle, sessionUserId: string): RoundSummary {
  const approvers = lifecycle.approvedBy.map((userId) => ({
    userId,
    you: userId === sessionUserId,
  }));
  return {
    approvers,
    count: approvers.length,
    required: lifecycle.requiredApprovals,
    waitingForAnother:
      lifecycle.status === "in_review" &&
      approvers.length > 0 &&
      approvers.length < lifecycle.requiredApprovals,
  };
}

/** One sentence on what the step did, from the rulebook's answer. */
export function stepOutcome(result: StepResult, sessionUserId: string): string {
  const { lifecycle } = result;
  const round = roundSummary(lifecycle, sessionUserId);
  switch (result.step) {
    case "submit":
      return lifecycle.highImpact
        ? t("ruleVersion.outcome.submittedHighImpact")
        : t("ruleVersion.outcome.submitted");
    case "approve":
      return lifecycle.status === "approved"
        ? t("ruleVersion.outcome.approved", { count: round.count, required: round.required })
        : t("ruleVersion.outcome.approvalRecorded", {
            count: round.count,
            required: round.required,
          });
    case "publish":
      return t("ruleVersion.outcome.published", {
        replaced: result.publication?.replacements.length ?? 0,
        moved: result.publication?.deadlineChanges.length ?? 0,
      });
    case "return":
      return t("ruleVersion.outcome.returned");
    case "withdraw":
      return t("ruleVersion.outcome.withdrawn");
  }
}
