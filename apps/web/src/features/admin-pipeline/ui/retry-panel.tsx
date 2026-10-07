"use client";

import { useId, useState } from "react";
import {
  Button,
  ConfirmDialog,
  Field,
  Label,
  RadioGroup,
  RadioGroupItem,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { fieldErrorOf } from "@/shared/lib/action-state";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { DOCUMENT_TYPE_LABELS } from "@/shared/ui/pipeline";
import {
  WriteOutcome,
  idempotencyKeyFor,
  useWriteAction,
  type WriteAction,
} from "@/shared/ui/write-outcome";
import {
  EXTRACTED_TYPES,
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  RETRY_FIELDS,
  STAGES,
  TYPES,
  isResendable,
  type Stage,
  type WriteResult,
} from "./pipeline-shared";

export interface RetryPanelProps {
  /** The retry action, bound to the document. */
  action: WriteAction<WriteResult>;
  /**
   * The Idempotency-Key minted for this render. A request the pipeline recorded without starting
   * (Temporal did not answer) or that got no answer keeps its own key until an answer settles it,
   * though the page renders again with a new one meanwhile.
   */
  idempotencyKey: string;
  /** "Example notice 1", for the dialog. */
  documentTitle: string;
}

const STAGE_OPTIONS: Readonly<Record<Stage, { label: MessageKey; help: MessageKey }>> = {
  parse: { label: "pipelineDocument.stage.parse", help: "pipelineDocument.stage.parseHelp" },
  classify: {
    label: "pipelineDocument.stage.classify",
    help: "pipelineDocument.stage.classifyHelp",
  },
  extract: { label: "pipelineDocument.stage.extract", help: "pipelineDocument.stage.extractHelp" },
};

const FIELD_NAMES = Object.values(RETRY_FIELDS);

/**
 * An admin's retry of a stored document: the stage its ingest starts again from (no new fetch),
 * optionally the type a person reads it as (which reclassifies it, beats the detector and brings
 * back a document set aside or whose triage was dismissed), and the reason the pipeline keeps. The
 * request carries the Idempotency-Key the page minted, so sending the same request again (an
 * answer that never came, or Temporal not answering) is answered with its attempt and never
 * records a second one; the form's Retry keeps that key too until the attempt is settled, so
 * pressing it again after such an answer is the same request, not a second attempt that would
 * leave the first never started. A dialog says what follows before anything is sent.
 */
export function RetryPanel({ action, idempotencyKey, documentTitle }: RetryPanelProps) {
  const id = useId();
  const [stage, setStage] = useState<Stage>("parse");
  const [type, setType] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  const state = attempt.last;
  const key = idempotencyKeyFor(attempt, idempotencyKey, isResendable);
  const typeLabel = type === "" ? null : t(DOCUMENT_TYPE_LABELS[type as (typeof TYPES)[number]]);
  const extractRefused = stage === "extract" && type !== "" && !EXTRACTED_TYPES.includes(type);

  const submit = () => {
    const formData = new FormData();
    formData.set(RETRY_FIELDS.stage, stage);
    if (type !== "") formData.set(RETRY_FIELDS.docType, type);
    formData.set(RETRY_FIELDS.reason, reason.trim());
    formData.set(IDEMPOTENCY_KEY_FIELD, key);
    setConfirming(false);
    send(formData);
  };

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="retry-panel"
      className="flex flex-col gap-4"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("pipelineDocument.retry.title")}
      </h2>
      <p className="max-w-prose text-sm text-fg-muted">{t("pipelineDocument.retry.intro")}</p>
      <div className="flex flex-col gap-3">
        <p id={`${id}-stage`} className="text-sm font-medium text-fg">
          {t("pipelineDocument.retry.stage")}
        </p>
        <RadioGroup
          value={stage}
          onValueChange={(value) => setStage(value as Stage)}
          aria-labelledby={`${id}-stage`}
          disabled={pending}
        >
          {STAGES.map((value) => (
            <div key={value} className="flex items-start gap-2">
              <RadioGroupItem value={value} id={`${id}-${value}`} className="mt-0.5" />
              <div className="flex flex-col gap-0.5">
                <Label htmlFor={`${id}-${value}`}>{t(STAGE_OPTIONS[value].label)}</Label>
                <p className="text-xs text-fg-muted">{t(STAGE_OPTIONS[value].help)}</p>
              </div>
            </div>
          ))}
        </RadioGroup>
        {fieldErrorOf(state, RETRY_FIELDS.stage) === undefined ? null : (
          <p role="alert" className="text-sm text-danger">
            {fieldErrorOf(state, RETRY_FIELDS.stage)}
          </p>
        )}
      </div>
      <Field
        id={`${id}-type`}
        label={t("pipelineDocument.retry.type")}
        description={
          extractRefused
            ? t("pipelineDocument.retry.typeNotExtracted")
            : t("pipelineDocument.retry.typeHelp")
        }
        error={fieldErrorOf(state, RETRY_FIELDS.docType)}
        className="max-w-md"
      >
        <Select
          value={type}
          disabled={pending}
          onChange={(event) => setType(event.target.value)}
          options={[
            { value: "", label: t("pipelineDocument.retry.keepType") },
            ...TYPES.map((value) => ({ value, label: t(DOCUMENT_TYPE_LABELS[value]) })),
          ]}
        />
      </Field>
      <Field
        id={`${id}-reason`}
        label={t("adminPipeline.reason")}
        description={t("adminPipeline.reasonHelp", { min: REASON_MIN_LENGTH })}
        error={fieldErrorOf(state, RETRY_FIELDS.reason)}
        required
        className="max-w-prose"
      >
        <Textarea
          value={reason}
          maxLength={REASON_MAX_LENGTH}
          disabled={pending}
          onChange={(event) => setReason(event.target.value)}
        />
      </Field>
      <div>
        <Button
          type="button"
          disabled={pending || reason.trim().length < REASON_MIN_LENGTH}
          aria-busy={pending || undefined}
          onClick={() => setConfirming(true)}
        >
          {t("pipelineDocument.retry.submit")}
        </Button>
      </div>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="retry-outcome"
        fieldNames={FIELD_NAMES}
        resendable={isResendable}
      />
      {confirming ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("pipelineDocument.retry.confirmTitle", { title: documentTitle })}
          description={
            typeLabel === null
              ? t("pipelineDocument.retry.confirmBody", { stage: t(STAGE_OPTIONS[stage].label) })
              : t("pipelineDocument.retry.confirmBodyTyped", {
                  stage: t(STAGE_OPTIONS[stage].label),
                  type: typeLabel,
                })
          }
          confirmLabel={t("pipelineDocument.retry.submit")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={submit}
        />
      ) : null}
    </section>
  );
}
