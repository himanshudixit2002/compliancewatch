import { REASON_MIN_LENGTH } from "@compliancewatch/ui";
import type {
  Publication,
  RuleVersionStatus,
  VersionLifecycle,
  WorkflowStep,
} from "@/entities/rule-version/types";
import { can, type Capability } from "@/shared/config/permissions";
import type { Principal } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import {
  NOTE_MAX_LENGTH,
  REASON_STEPS,
  STEP_FIELDS,
  stepLabel,
  type StepResult,
} from "../ui/workflow-shared";

/**
 * The publish workflow of a rule version (ADR-006): the steps the rulebook offers from each
 * status, as its route summaries state them (submit a draft; approve a version under review;
 * publish an approved one; return one under review or approved to draft; withdraw a published
 * one). The page offers those; the rulebook decides, and every refusal it answers (a second
 * approval by the same reviewer, missing or unverified citations, an overlap, a relation that
 * cannot take effect) is shown next to the step as it says it.
 */
export const STEPS_BY_STATUS: Readonly<Record<RuleVersionStatus, readonly WorkflowStep[]>> = {
  draft: ["submit"],
  in_review: ["approve", "return"],
  approved: ["publish", "return"],
  published: ["withdraw"],
  superseded: [],
  withdrawn: [],
};

export const WORKFLOW_STEPS: readonly WorkflowStep[] = [
  "submit",
  "approve",
  "publish",
  "return",
  "withdraw",
];

export function stepsFor(status: string): readonly WorkflowStep[] {
  return STEPS_BY_STATUS[status as RuleVersionStatus] ?? [];
}

/**
 * Who takes each step (D-043, D-061). Every regulatory role submits a draft and returns a version
 * to draft; approving, publishing and withdrawing are a reviewer's or an admin's, as the role
 * table says ("reviewer: approves and publishes"). The rulebook's shared review token would take
 * any step from any caller, so the page offers a step only to its roles and `takeStep` checks the
 * role again before any request.
 */
export const STEP_CAPABILITY: Readonly<Record<WorkflowStep, Capability>> = {
  submit: "admin.review",
  return: "admin.review",
  approve: "admin.review.approve",
  publish: "admin.publish",
  withdraw: "admin.publish",
};

export function mayTake(principal: Principal | null, step: WorkflowStep): boolean {
  return can(principal, STEP_CAPABILITY[step]);
}

/**
 * The steps the status allows, split by the session's roles: the ones it may take, and the ones
 * left to a reviewer or an admin, which the panel names without offering them.
 */
export function stepsOffered(
  status: string,
  principal: Principal | null,
): { steps: WorkflowStep[]; reserved: WorkflowStep[] } {
  const all = stepsFor(status);
  return {
    steps: all.filter((step) => mayTake(principal, step)),
    reserved: all.filter((step) => !mayTake(principal, step)),
  };
}

/** The refusal of a step the session's roles do not take, said before any request. */
export function reservedStepRefusal(step: WorkflowStep): string {
  return t("ruleVersion.workflow.reservedRefusal", { step: stepLabel(step) });
}

export function isWorkflowStep(value: string): value is WorkflowStep {
  return (WORKFLOW_STEPS as readonly string[]).includes(value);
}

export type ParsedStep =
  | { ok: true; step: WorkflowStep; note: string; highImpact: boolean }
  | { ok: false; fieldErrors: FieldErrors };

/** The step form: which step, the note (a reason of ten characters or more for two of them). */
export function parseStepForm(formData: FormData): ParsedStep {
  const step = String(formData.get(STEP_FIELDS.step) ?? "");
  const note = String(formData.get(STEP_FIELDS.note) ?? "").trim();
  const flag = String(formData.get(STEP_FIELDS.highImpact) ?? "");
  if (!isWorkflowStep(step)) {
    return {
      ok: false,
      fieldErrors: { [STEP_FIELDS.step]: [t("ruleVersion.workflow.unknownStep")] },
    };
  }
  if (note.length > NOTE_MAX_LENGTH) {
    return {
      ok: false,
      fieldErrors: {
        [STEP_FIELDS.note]: [t("ruleVersion.workflow.noteTooLong", { max: NOTE_MAX_LENGTH })],
      },
    };
  }
  if (REASON_STEPS.has(step) && note.length < REASON_MIN_LENGTH) {
    return {
      ok: false,
      fieldErrors: {
        [STEP_FIELDS.note]: [t("ruleVersion.workflow.reasonRequired", { min: REASON_MIN_LENGTH })],
      },
    };
  }
  return { ok: true, step, note, highImpact: flag === "on" || flag === "true" };
}

/** A step's answer as plain data for the panel: the lifecycle, and a publication's effects. */
export function stepResult(step: WorkflowStep, answer: VersionLifecycle | Publication): StepResult {
  const lifecycle: VersionLifecycle = {
    ruleVersionId: answer.ruleVersionId,
    ruleId: answer.ruleId,
    version: answer.version,
    status: answer.status,
    seedStatus: answer.seedStatus,
    highImpact: answer.highImpact,
    effectiveFrom: answer.effectiveFrom,
    effectiveTo: answer.effectiveTo,
    submittedAt: answer.submittedAt,
    publishedAt: answer.publishedAt,
    approvedBy: answer.approvedBy,
    requiredApprovals: answer.requiredApprovals,
    events: answer.events,
  };
  const publication =
    "correlationId" in answer
      ? {
          correlationId: answer.correlationId,
          replacements: answer.replacements,
          deadlineChanges: answer.deadlineChanges,
          attributeKeys: answer.attributeKeys,
        }
      : null;
  return { step, lifecycle, publication };
}
