"use client";

import { useId, useState } from "react";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Field,
  Label,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { RULE_REJECT_REASONS, type RuleRejectReason } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import {
  DECIDE_FIELDS,
  LIMITS,
  type ApprovalsView,
  type DecideView,
  type WriteResult,
} from "./form-shared";
import { PersonName, WriteResultView } from "./write-result";

export interface DecidePanelProps {
  action: WriteAction<WriteResult>;
  /** What may be decided now; null once the task is decided (the answer stays). */
  view: DecideView | null;
  approvals: ApprovalsView | null;
}

type Decision = "approve" | "return" | "reject";

const REASON_KEYS: Readonly<Record<RuleRejectReason, MessageKey>> = {
  not_a_rule: "workbench.rejectReason.not_a_rule",
  wrong_extraction: "workbench.rejectReason.wrong_extraction",
  duplicate: "workbench.rejectReason.duplicate",
  out_of_scope: "workbench.rejectReason.out_of_scope",
  unparseable: "workbench.rejectReason.unparseable",
};

/** The approvals of the round: "1 of 2 approvals", with who approved. */
export function Approvals({ approvals }: { approvals: ApprovalsView }) {
  return (
    <div className="flex flex-col gap-1 text-sm" data-slot="approvals">
      <p className="text-fg">
        {t("workbench.approvals.count", { count: approvals.count, required: approvals.required })}
        {approvals.waitingForAnother ? ` ${t("workbench.approvals.another")}` : null}
      </p>
      {approvals.approvers.length === 0 ? null : (
        <ul className="ml-5 list-disc" data-slot="approvers">
          {approvals.approvers.map((approver) => (
            <li key={approver.userId} data-approver={approver.userId}>
              <PersonName person={approver} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Deciding the task: approve (a reviewer's or an admin's; it submits a draft and approves it, and
 * may first tag the version high impact, which then needs two different approvers), return it for
 * rework with a note, or reject it with a note (and a candidate's reason). Each opens a dialog
 * that says what the rulebook records. The panel stays on the page after the decision, so the
 * answer (the task, the version, the candidate and the next task a return opened) is still there.
 */
export function DecidePanel({ action, view, approvals }: DecidePanelProps) {
  const id = useId();
  const [highImpact, setHighImpact] = useState(view?.highImpact ?? false);
  const [approveNote, setApproveNote] = useState("");
  const [returnNote, setReturnNote] = useState("");
  const [rejectNote, setRejectNote] = useState("");
  const [reason, setReason] = useState<RuleRejectReason | "">("");
  const [confirming, setConfirming] = useState<Decision | null>(null);
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);

  const decide = (decision: Decision) => {
    const formData = new FormData();
    formData.set(DECIDE_FIELDS.decision, decision);
    if (decision === "approve") {
      formData.set(DECIDE_FIELDS.note, approveNote.trim());
      if (highImpact) formData.set(DECIDE_FIELDS.highImpact, "on");
    } else if (decision === "return") {
      formData.set(DECIDE_FIELDS.note, returnNote.trim());
    } else {
      formData.set(DECIDE_FIELDS.note, rejectNote.trim());
      if (reason !== "") formData.set(DECIDE_FIELDS.reason, reason);
    }
    setConfirming(null);
    send(formData);
  };

  const rejectReady = rejectNote.trim() !== "" && (view?.candidateTask !== true || reason !== "");

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="decide-panel"
      className="flex flex-col gap-4"
    >
      <h3 id={`${id}-heading`} className="text-base font-semibold text-fg">
        {t("workbench.decide.heading")}
      </h3>
      {approvals === null ? null : <Approvals approvals={approvals} />}
      {view === null ? (
        <p className="text-sm text-fg-muted" data-slot="decide-closed">
          {t("workbench.decide.closed")}
        </p>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3" data-decision="approve">
            <h4 className="text-sm font-semibold text-fg">
              {t("workbench.decide.approveHeading")}
            </h4>
            {view.canApprove ? (
              <>
                <p className="max-w-prose text-sm text-fg-muted">
                  {t("workbench.decide.approveIntro")}
                </p>
                <div className="flex items-start gap-2">
                  <Checkbox
                    id={`${id}-high-impact`}
                    checked={highImpact}
                    disabled={pending || view.highImpact}
                    onCheckedChange={(checked) => setHighImpact(checked === true)}
                  />
                  <Label htmlFor={`${id}-high-impact`} className="flex flex-col items-start gap-1">
                    <span>{t("workbench.decide.highImpact")}</span>
                    <span className="text-xs font-normal text-fg-muted">
                      {view.highImpact
                        ? t("workbench.decide.highImpactSet")
                        : t("workbench.decide.highImpactHelp")}
                    </span>
                  </Label>
                </div>
                <Field
                  id={`${id}-approve-note`}
                  label={t("workbench.decide.noteOptional")}
                  description={t("workbench.decide.noteHelp", { max: LIMITS.note })}
                >
                  <Textarea
                    value={approveNote}
                    rows={2}
                    maxLength={LIMITS.note}
                    disabled={pending}
                    onChange={(event) => setApproveNote(event.target.value)}
                  />
                </Field>
                <div>
                  <Button
                    type="button"
                    disabled={pending}
                    aria-busy={pending || undefined}
                    onClick={() => setConfirming("approve")}
                  >
                    {t("workbench.decide.approve")}
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-fg-muted" data-slot="approve-blocked">
                {view.approveBlocked}
              </p>
            )}
          </div>
          {view.canReturn ? (
            <div className="flex flex-col gap-3" data-decision="return">
              <h4 className="text-sm font-semibold text-fg">
                {t("workbench.decide.returnHeading")}
              </h4>
              <Field
                id={`${id}-return-note`}
                label={t("workbench.decide.noteRequired")}
                description={t("workbench.decide.returnHelp")}
                required
              >
                <Textarea
                  value={returnNote}
                  rows={2}
                  maxLength={LIMITS.note}
                  disabled={pending}
                  onChange={(event) => setReturnNote(event.target.value)}
                />
              </Field>
              <div>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={pending || returnNote.trim() === ""}
                  aria-busy={pending || undefined}
                  onClick={() => setConfirming("return")}
                >
                  {t("workbench.decide.return")}
                </Button>
              </div>
            </div>
          ) : null}
          {view.canReject ? (
            <div className="flex flex-col gap-3" data-decision="reject">
              <h4 className="text-sm font-semibold text-fg">
                {t("workbench.decide.rejectHeading")}
              </h4>
              <p className="max-w-prose text-sm text-fg-muted">
                {view.candidateTask
                  ? t("workbench.decide.rejectCandidateIntro")
                  : t("workbench.decide.rejectIntro")}
              </p>
              {view.candidateTask ? (
                <Field id={`${id}-reason`} label={t("workbench.decide.reason")} required>
                  <Select
                    value={reason}
                    placeholder={t("workbench.decide.reasonChoose")}
                    disabled={pending}
                    onChange={(event) => setReason(event.target.value as RuleRejectReason)}
                    options={RULE_REJECT_REASONS.map((value) => ({
                      value,
                      label: t(REASON_KEYS[value]),
                    }))}
                  />
                </Field>
              ) : null}
              <Field
                id={`${id}-reject-note`}
                label={t("workbench.decide.noteRequired")}
                description={t("workbench.decide.rejectHelp")}
                required
              >
                <Textarea
                  value={rejectNote}
                  rows={2}
                  maxLength={LIMITS.note}
                  disabled={pending}
                  onChange={(event) => setRejectNote(event.target.value)}
                />
              </Field>
              <div>
                <Button
                  type="button"
                  variant="danger"
                  disabled={pending || !rejectReady}
                  aria-busy={pending || undefined}
                  onClick={() => setConfirming("reject")}
                >
                  {t("workbench.decide.reject")}
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      )}
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="decide-outcome"
        renderValue={(value) => <WriteResultView result={value} />}
      />
      {confirming === "approve" ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirming(null);
          }}
          title={t("workbench.decide.approveTitle")}
          description={
            highImpact
              ? t("workbench.decide.approveConfirmHigh")
              : t("workbench.decide.approveConfirm")
          }
          confirmLabel={t("workbench.decide.approve")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={() => decide("approve")}
        />
      ) : null}
      {confirming === "return" ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirming(null);
          }}
          title={t("workbench.decide.returnTitle")}
          description={t("workbench.decide.returnConfirm")}
          confirmLabel={t("workbench.decide.return")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={() => decide("return")}
        />
      ) : null}
      {confirming === "reject" ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirming(null);
          }}
          title={t("workbench.decide.rejectTitle")}
          description={
            view?.candidateTask === true
              ? t("workbench.decide.rejectCandidateConfirm")
              : t("workbench.decide.rejectConfirm")
          }
          confirmLabel={t("workbench.decide.reject")}
          cancelLabel={t("common.cancel")}
          destructive
          pending={pending}
          onConfirm={() => decide("reject")}
        />
      ) : null}
    </section>
  );
}
