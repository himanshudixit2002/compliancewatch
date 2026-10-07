"use client";

import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import {
  Banner,
  Button,
  Checkbox,
  ConfirmDialog,
  ErrorState,
  Field,
  Label,
  ReasonDialog,
  Textarea,
} from "@compliancewatch/ui";
import type { WorkflowStep } from "@/entities/rule-version/types";
import { t } from "@/shared/i18n";
import { idleAction, type ActionProblem, type ActionState } from "@/shared/lib/action-state";
import {
  NOTE_MAX_LENGTH,
  REASON_STEPS,
  STEP_FIELDS,
  hasRound,
  roundSummary,
  stepDescription,
  stepLabel,
  stepOutcome,
  type AccessView,
  type StepResult,
} from "./workflow-shared";

export type TakeStepAction = (
  state: ActionState<StepResult>,
  formData: FormData,
) => Promise<ActionState<StepResult>>;

export interface WorkflowPanelProps {
  /** The step action, bound to the version. */
  action: TakeStepAction;
  /** The steps the version's status allows that the session's roles take. */
  steps: readonly WorkflowStep[];
  /** The steps the status allows that are a reviewer's or an admin's: named, not offered. */
  reserved: readonly WorkflowStep[];
  access: AccessView;
  version: number;
  highImpact: boolean;
  /** The signed-in analyst, marked among the approvers by name. */
  sessionUserId: string;
  sessionName: string;
}

interface Attempt {
  /** The last answer the rulebook gave to a step, kept across a later refusal. */
  last: StepResult | null;
  /** The step the rulebook (or the form check) refused last, with why. */
  refused: { step: WorkflowStep; problem?: ActionProblem; messages: readonly string[] } | null;
  count: number;
}

function Approvals({
  result,
  sessionUserId,
  sessionName,
}: {
  result: StepResult;
  sessionUserId: string;
  sessionName: string;
}) {
  if (!hasRound(result.lifecycle)) return null;
  const round = roundSummary(result.lifecycle, sessionUserId);
  return (
    <div data-slot="round" className="flex flex-col gap-1 text-sm">
      <p>
        {t("ruleVersion.round.count", { count: round.count, required: round.required })}
        {round.waitingForAnother ? ` ${t("ruleVersion.round.needsAnother")}` : null}
      </p>
      {round.approvers.length === 0 ? (
        <p className="text-fg-muted">{t("ruleVersion.round.none")}</p>
      ) : (
        <>
          <p className="text-fg-muted">{t("ruleVersion.round.approvedBy")}</p>
          <ul className="ml-5 list-disc" data-slot="approvers">
            {round.approvers.map((approver) => (
              <li key={approver.userId} data-approver={approver.userId}>
                {approver.you ? (
                  t("ruleVersion.round.you", { name: sessionName })
                ) : (
                  <code className="font-mono text-xs">{approver.userId}</code>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * The publish workflow of a version: the steps its status allows the session's roles, each
 * confirmed in a dialog that says what the rulebook records (a reason for return and withdraw),
 * the outcome of the last step with the approvers of the round as the rulebook reported them, and
 * any refusal (the rulebook's problem: a second approval by the same reviewer, missing citations,
 * an overlap) right under the step it refused. Approving, publishing and withdrawing are a
 * reviewer's or an admin's: for anyone else the panel names them and offers none (D-043). The
 * acting analyst is the session's user; nothing here names another, and no approval is ever sent
 * as synthetic.
 */
export function WorkflowPanel({
  action,
  steps,
  reserved,
  access,
  version,
  highImpact,
  sessionUserId,
  sessionName,
}: WorkflowPanelProps) {
  const id = useId();
  const [open, setOpen] = useState<WorkflowStep | null>(null);
  const [note, setNote] = useState("");
  const [markHighImpact, setMarkHighImpact] = useState(highImpact);
  const [attempt, dispatch, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const step = String(formData.get(STEP_FIELDS.step) ?? "") as WorkflowStep;
      const state = await action(idleAction(), formData);
      if (state.status === "ok" && state.value !== undefined) {
        return { last: state.value, refused: null, count: previous.count + 1 };
      }
      const messages =
        state.status === "error"
          ? [
              ...(state.formErrors ?? []),
              ...Object.values(state.fieldErrors ?? {}).flatMap((list) => [...list]),
            ]
          : [];
      return {
        last: previous.last,
        refused: {
          step,
          ...(state.status === "error" && state.problem !== undefined
            ? { problem: state.problem }
            : {}),
          messages,
        },
        count: previous.count + 1,
      };
    },
    { last: null, refused: null, count: 0 },
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  const refusedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (attempt.count === 0) return;
    if (attempt.refused === null) outcomeRef.current?.focus();
    else refusedRef.current?.focus();
  }, [attempt]);

  const close = () => {
    setOpen(null);
    setNote("");
  };

  const send = (step: WorkflowStep, text: string) => {
    const formData = new FormData();
    formData.set(STEP_FIELDS.step, step);
    formData.set(STEP_FIELDS.note, text);
    if (step === "submit" && markHighImpact) formData.set(STEP_FIELDS.highImpact, "on");
    close();
    startTransition(() => dispatch(formData));
  };

  const disabled = !access.allowed || pending;

  return (
    <section aria-labelledby={`${id}-heading`} data-slot="workflow" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
          {t("ruleVersion.workflow.heading")}
        </h2>
        <p className="max-w-prose text-sm text-fg-muted">
          {highImpact
            ? t("ruleVersion.workflow.twoApprovers")
            : t("ruleVersion.workflow.oneApprover")}
        </p>
      </div>
      {access.allowed ? null : (
        <Banner tone="warning" title={access.title}>
          {access.detail ?? null}
        </Banner>
      )}
      <div
        ref={outcomeRef}
        tabIndex={-1}
        role="status"
        data-slot="workflow-outcome"
        className="flex flex-col gap-2 outline-none"
      >
        {attempt.last === null ? (
          <p className="max-w-prose text-sm text-fg-muted">{t("ruleVersion.round.unknown")}</p>
        ) : (
          <>
            <p className="text-sm font-medium text-fg">
              {stepOutcome(attempt.last, sessionUserId)}
            </p>
            <Approvals
              result={attempt.last}
              sessionUserId={sessionUserId}
              sessionName={sessionName}
            />
          </>
        )}
      </div>
      {reserved.length === 0 ? null : (
        <p className="max-w-prose text-sm text-fg-muted" data-slot="workflow-reserved">
          {t("ruleVersion.workflow.reserved", { steps: reserved.map(stepLabel).join(", ") })}
        </p>
      )}
      {steps.length === 0 ? (
        reserved.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("ruleVersion.workflow.noSteps")}</p>
        ) : null
      ) : (
        <ul className="flex flex-col gap-3" data-slot="workflow-steps">
          {steps.map((step) => (
            <li key={step} data-step={step} className="flex flex-col gap-2">
              <div>
                <Button
                  type="button"
                  variant={
                    step === "withdraw" ? "danger" : step === "return" ? "secondary" : "primary"
                  }
                  disabled={disabled}
                  aria-busy={(pending && open === null) || undefined}
                  onClick={() => {
                    setNote("");
                    setMarkHighImpact(highImpact);
                    setOpen(step);
                  }}
                >
                  {stepLabel(step)}
                </Button>
              </div>
              {attempt.refused?.step === step ? (
                <div
                  ref={refusedRef}
                  tabIndex={-1}
                  data-slot="step-refusal"
                  className="flex flex-col gap-1 outline-none"
                >
                  {attempt.refused.problem === undefined ? null : (
                    <ErrorState
                      title={attempt.refused.problem.title}
                      detail={attempt.refused.problem.detail}
                      correlationId={attempt.refused.problem.correlationId || undefined}
                    />
                  )}
                  {attempt.refused.messages.map((message, index) => (
                    <p key={index} role="alert" className="text-sm text-danger">
                      {message}
                    </p>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {open !== null && REASON_STEPS.has(open) ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) close();
          }}
          title={t("ruleVersion.dialog.title", { step: stepLabel(open), version })}
          description={stepDescription(open)}
          label={t("ruleVersion.dialog.reason")}
          confirmLabel={stepLabel(open)}
          cancelLabel={t("common.cancel")}
          destructive={open === "withdraw"}
          pending={pending}
          onConfirm={(reason) => send(open, reason)}
        />
      ) : null}
      {open !== null && !REASON_STEPS.has(open) ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) close();
          }}
          title={t("ruleVersion.dialog.title", { step: stepLabel(open), version })}
          description={stepDescription(open)}
          confirmLabel={stepLabel(open)}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={() => send(open, note.trim())}
        >
          <div className="flex flex-col gap-4">
            {open === "submit" ? (
              <div className="flex items-start gap-2">
                <Checkbox
                  id={`${id}-high-impact`}
                  checked={markHighImpact}
                  disabled={highImpact}
                  onCheckedChange={(checked) => setMarkHighImpact(checked === true)}
                />
                <div className="flex flex-col gap-1">
                  <Label htmlFor={`${id}-high-impact`}>{t("ruleVersion.dialog.highImpact")}</Label>
                  <p className="text-sm text-fg-muted">
                    {highImpact
                      ? t("ruleVersion.dialog.highImpactKept")
                      : t("ruleVersion.dialog.highImpactHelp")}
                  </p>
                </div>
              </div>
            ) : null}
            <Field
              id={`${id}-note`}
              label={t("ruleVersion.dialog.note")}
              description={t("ruleVersion.dialog.noteHelp", { max: NOTE_MAX_LENGTH })}
            >
              <Textarea
                value={note}
                maxLength={NOTE_MAX_LENGTH}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
          </div>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
