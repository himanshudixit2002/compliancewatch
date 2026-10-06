"use client";

import type { Route } from "next";
import Link from "next/link";
import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import { Button, ConfirmDialog, ErrorState, Field, Select, Textarea } from "@compliancewatch/ui";
import { CANDIDATE_REJECT_REASONS, type CandidateRejectReason } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import {
  APPROVE_FIELDS,
  NOTE_MAX_LENGTH,
  REJECT_FIELDS,
  candidateRejectReasonLabel,
  type CandidateDecisionResult,
  type VersionOption,
} from "./decision-shared";

export type CandidateAction = (
  state: ActionState<CandidateDecisionResult>,
  formData: FormData,
) => Promise<ActionState<CandidateDecisionResult>>;

export interface CandidateDecisionsProps {
  /** The approve action, bound to the candidate. */
  approve: CandidateAction;
  /** The reject action, bound to the candidate. */
  reject: CandidateAction;
  /** Only an open candidate takes a decision. */
  open: boolean;
  statusLabel: string;
  /** "Extends deadline: Form EXAMPLE-1", for the dialogs. */
  name: string;
  /** Approving needs the affected version. */
  needsTarget: boolean;
  /** The target is aligned to an entity, so a version is optional for it. */
  aligned: boolean;
  /** The versions offered; null when they could not be read. */
  options: { from: readonly VersionOption[]; target: readonly VersionOption[] } | null;
  /** Why the versions are missing, when their read failed. */
  optionsError: { title: string; detail?: string; correlationId?: string } | null;
}

type Sent = "approve" | "reject" | null;

/**
 * Deciding an open candidate: approve it into a rule relation from a draft version (and onto the
 * affected version where the relation needs one), or reject it with one of the rulebook's
 * reasons, each with an optional note and a dialog that says what the rulebook records. The one
 * who decided is the signed-in user, set on the server. The panel stays on the page after the
 * decision, so the rulebook's answer is still there to read.
 */
export function CandidateDecisions({
  approve,
  reject,
  open,
  statusLabel,
  name,
  needsTarget,
  aligned,
  options,
  optionsError,
}: CandidateDecisionsProps) {
  const id = useId();
  const [from, setFrom] = useState("");
  const [target, setTarget] = useState("");
  const [approveNote, setApproveNote] = useState("");
  const [reason, setReason] = useState<CandidateRejectReason | "">("");
  const [rejectNote, setRejectNote] = useState("");
  const [confirming, setConfirming] = useState<Sent>(null);
  const [sent, setSent] = useState<Sent>(null);
  const [count, setCount] = useState(0);
  const [approved, dispatchApprove, approving] = useActionState(
    async (_previous: ActionState<CandidateDecisionResult>, formData: FormData) =>
      approve(idleAction(), formData),
    idleAction<CandidateDecisionResult>(),
  );
  const [rejected, dispatchReject, rejecting] = useActionState(
    async (_previous: ActionState<CandidateDecisionResult>, formData: FormData) =>
      reject(idleAction(), formData),
    idleAction<CandidateDecisionResult>(),
  );
  const pending = approving || rejecting;
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (count > 0 && !pending) outcomeRef.current?.focus();
  }, [count, pending]);

  const state = sent === "reject" ? rejected : approved;
  const fromOptions = options?.from ?? [];
  const targetOptions = options?.target ?? [];
  const canApprove = from !== "" && (!needsTarget || target !== "");

  const sendApproval = () => {
    const formData = new FormData();
    formData.set(APPROVE_FIELDS.fromRuleVersionId, from);
    if (target !== "") formData.set(APPROVE_FIELDS.targetRuleVersionId, target);
    formData.set(APPROVE_FIELDS.note, approveNote.trim());
    setConfirming(null);
    setSent("approve");
    setCount((value) => value + 1);
    startTransition(() => dispatchApprove(formData));
  };
  const sendRejection = () => {
    if (reason === "") return;
    const formData = new FormData();
    formData.set(REJECT_FIELDS.reason, reason);
    formData.set(REJECT_FIELDS.note, rejectNote.trim());
    setConfirming(null);
    setSent("reject");
    setCount((value) => value + 1);
    startTransition(() => dispatchReject(formData));
  };

  const fromLabel = fromOptions.find((option) => option.value === from)?.label ?? from;
  const targetLabel = targetOptions.find((option) => option.value === target)?.label ?? target;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];

  return (
    <div className="flex flex-col gap-8" data-slot="candidate-decisions">
      {!open ? (
        <p className="text-sm text-fg-muted" data-slot="candidate-closed">
          {t("relationReview.closedNote", { status: statusLabel })}
        </p>
      ) : (
        <>
          <section aria-labelledby={`${id}-approve`} className="flex flex-col gap-4">
            <h2 id={`${id}-approve`} className="text-lg font-semibold text-fg">
              {t("relationReview.approve.title")}
            </h2>
            <p className="max-w-prose text-sm text-fg-muted">{t("relationReview.approve.intro")}</p>
            {optionsError === null ? null : (
              <ErrorState
                title={optionsError.title}
                detail={optionsError.detail}
                correlationId={optionsError.correlationId || undefined}
              />
            )}
            {options !== null && fromOptions.length === 0 ? (
              <p className="text-sm text-fg-muted" data-slot="no-drafts">
                {t("relationReview.approve.noDrafts")}
              </p>
            ) : null}
            <Field
              id={`${id}-from`}
              label={t("relationReview.approve.from")}
              description={t("relationReview.approve.fromHelp")}
              error={fieldErrorOf(approved, APPROVE_FIELDS.fromRuleVersionId)}
              required
              className="max-w-2xl"
            >
              <Select
                value={from}
                placeholder={t("relationReview.approve.fromPlaceholder")}
                disabled={pending || fromOptions.length === 0}
                onChange={(event) => setFrom(event.target.value)}
                options={fromOptions}
              />
            </Field>
            <Field
              id={`${id}-target`}
              label={t("relationReview.approve.target")}
              description={
                needsTarget
                  ? t("relationReview.approve.targetRequiredHelp")
                  : aligned
                    ? t("relationReview.approve.targetEntityHelp")
                    : t("relationReview.approve.targetUnalignedHelp")
              }
              error={fieldErrorOf(approved, APPROVE_FIELDS.targetRuleVersionId)}
              required={needsTarget}
              className="max-w-2xl"
            >
              <Select
                value={target}
                disabled={pending || targetOptions.length === 0}
                onChange={(event) => setTarget(event.target.value)}
                options={[
                  {
                    value: "",
                    label: needsTarget
                      ? t("relationReview.approve.targetPlaceholder")
                      : t("relationReview.approve.targetNone"),
                    disabled: needsTarget,
                  },
                  ...targetOptions,
                ]}
              />
            </Field>
            <Field
              id={`${id}-approve-note`}
              label={t("relationReview.note")}
              description={t("relationReview.noteHelp", { max: NOTE_MAX_LENGTH })}
              error={fieldErrorOf(approved, APPROVE_FIELDS.note)}
              className="max-w-prose"
            >
              <Textarea
                value={approveNote}
                maxLength={NOTE_MAX_LENGTH}
                disabled={pending}
                onChange={(event) => setApproveNote(event.target.value)}
              />
            </Field>
            <div>
              <Button
                type="button"
                disabled={!canApprove || pending}
                aria-busy={approving || undefined}
                onClick={() => setConfirming("approve")}
              >
                {t("relationReview.approve.submit")}
              </Button>
            </div>
          </section>
          <section aria-labelledby={`${id}-reject`} className="flex flex-col gap-4">
            <h2 id={`${id}-reject`} className="text-lg font-semibold text-fg">
              {t("relationReview.reject.title")}
            </h2>
            <Field
              id={`${id}-reason`}
              label={t("relationReview.reject.reason")}
              error={fieldErrorOf(rejected, REJECT_FIELDS.reason)}
              required
              className="max-w-md"
            >
              <Select
                value={reason}
                placeholder={t("relationReview.reject.reasonPlaceholder")}
                disabled={pending}
                onChange={(event) => setReason(event.target.value as CandidateRejectReason)}
                options={CANDIDATE_REJECT_REASONS.map((value) => ({
                  value,
                  label: candidateRejectReasonLabel(value),
                }))}
              />
            </Field>
            <Field
              id={`${id}-reject-note`}
              label={t("relationReview.note")}
              description={t("relationReview.noteHelp", { max: NOTE_MAX_LENGTH })}
              error={fieldErrorOf(rejected, REJECT_FIELDS.note)}
              className="max-w-prose"
            >
              <Textarea
                value={rejectNote}
                maxLength={NOTE_MAX_LENGTH}
                disabled={pending}
                onChange={(event) => setRejectNote(event.target.value)}
              />
            </Field>
            <div>
              <Button
                type="button"
                variant="danger"
                disabled={reason === "" || pending}
                aria-busy={rejecting || undefined}
                onClick={() => setConfirming("reject")}
              >
                {t("relationReview.reject.submit")}
              </Button>
            </div>
          </section>
          <div className="flex flex-col gap-1 text-sm text-fg-muted" data-slot="recorded">
            <p className="font-medium text-fg">{t("relationReview.recordedTitle")}</p>
            <p>{t("relationReview.recorded")}</p>
          </div>
        </>
      )}
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="candidate-outcome"
        className="flex flex-col gap-3 outline-none"
      >
        {state.status === "ok" && state.value !== undefined ? (
          <div
            role="status"
            className="flex flex-col gap-1"
            data-slot={state.value.kind === "already" ? "candidate-already" : "candidate-done"}
          >
            <p className="text-sm font-medium text-fg">{state.value.message}</p>
            {state.value.graphHref === null ? null : (
              <Link
                href={state.value.graphHref as Route}
                className="text-sm text-primary underline-offset-2 hover:underline"
              >
                {t("relationReview.approve.openGraph")}
              </Link>
            )}
          </div>
        ) : state.status === "error" ? (
          <>
            {state.problem === undefined ? null : (
              <ErrorState
                title={state.problem.title}
                detail={state.problem.detail}
                correlationId={state.problem.correlationId || undefined}
              />
            )}
            {formErrors.map((message, index) => (
              <p key={index} role="alert" className="text-sm text-danger">
                {message}
              </p>
            ))}
          </>
        ) : null}
      </div>
      {confirming === "approve" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(null);
          }}
          title={t("relationReview.approve.dialogTitle", { name })}
          description={
            target === ""
              ? t("relationReview.approve.confirmEntity", { from: fromLabel })
              : t("relationReview.approve.confirmVersion", { from: fromLabel, target: targetLabel })
          }
          confirmLabel={t("relationReview.approve.submit")}
          cancelLabel={t("common.cancel")}
          pending={approving}
          onConfirm={sendApproval}
        />
      ) : null}
      {confirming === "reject" && reason !== "" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(null);
          }}
          title={t("relationReview.reject.dialogTitle", { name })}
          description={t("relationReview.reject.confirm", {
            reason: candidateRejectReasonLabel(reason),
          })}
          confirmLabel={t("relationReview.reject.submit")}
          cancelLabel={t("common.cancel")}
          destructive
          pending={rejecting}
          onConfirm={sendRejection}
        />
      ) : null}
    </div>
  );
}
