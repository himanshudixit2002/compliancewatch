"use client";

import { useId, useState } from "react";
import {
  Button,
  ConfirmDialog,
  Field,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  ReasonDialog,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf } from "@/shared/lib/action-state";
import { DOCUMENT_TYPE_LABELS } from "@/shared/ui/pipeline";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import {
  DISMISS_FIELDS,
  EXTRACTED_TYPES,
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  RESOLVE_FIELDS,
  TRANSCRIPT_TITLE_MAX,
  TYPES,
  isResendable,
  type WriteResult,
} from "./pipeline-shared";
import { blockCounts, readTranscript } from "./transcript";

export interface TaskPanelProps {
  kind: "manual_parse" | "triage";
  /** The resolve and dismiss actions, bound to the task (and its kind). */
  resolve: WriteAction<WriteResult>;
  dismiss: WriteAction<WriteResult>;
  documentTitle: string;
}

/** Which of the two writes a request is, so one outcome region answers both. */
const INTENT = "intent";

const FIELD_NAMES = [...Object.values(RESOLVE_FIELDS), DISMISS_FIELDS.reason];

/**
 * An open task's resolution, for an admin: a manual parse resolved with the document typed in
 * (the transcript, read here as the pipeline will read it), a triage with the decision (relevant
 * and of a type, or not a regulatory document), each with the reason the pipeline keeps; or the
 * task dismissed with a reason. A resolution sent again, the same one, is answered as the first
 * was and said as done. Dialogs say what follows before anything is sent.
 */
export function TaskPanel({ kind, resolve, dismiss, documentTitle }: TaskPanelProps) {
  const id = useId();
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [relevance, setRelevance] = useState<"relevant" | "irrelevant" | "">("");
  const [type, setType] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState<"resolve" | "dismiss" | null>(null);
  const action: WriteAction<WriteResult> = async (state, formData) =>
    formData.get(INTENT) === "dismiss" ? dismiss(state, formData) : resolve(state, formData);
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  const state = attempt.last;
  const read = kind === "manual_parse" ? readTranscript(transcript) : null;
  const counts = read === null ? null : blockCounts(read.blocks);
  const reasonReady = reason.trim().length >= REASON_MIN_LENGTH;
  const ready =
    reasonReady &&
    (kind === "manual_parse"
      ? read !== null && read.ok
      : relevance === "irrelevant" || (relevance === "relevant" && type !== ""));
  const typeLabel = type === "" ? "" : t(DOCUMENT_TYPE_LABELS[type as (typeof TYPES)[number]]);

  const sendResolution = () => {
    const formData = new FormData();
    formData.set(INTENT, "resolve");
    formData.set(RESOLVE_FIELDS.reason, reason.trim());
    if (kind === "manual_parse") {
      formData.set(RESOLVE_FIELDS.title, title.trim());
      formData.set(RESOLVE_FIELDS.transcript, transcript);
    } else {
      formData.set(RESOLVE_FIELDS.relevance, relevance);
      if (relevance === "relevant") formData.set(RESOLVE_FIELDS.docType, type);
    }
    setConfirming(null);
    send(formData);
  };

  const transcriptErrors =
    fieldErrorOf(state, RESOLVE_FIELDS.transcript) === undefined
      ? read !== null && !read.ok && transcript.trim() !== ""
        ? read.errors
        : undefined
      : state.status === "error"
        ? state.fieldErrors?.[RESOLVE_FIELDS.transcript]
        : undefined;

  return (
    <div className="flex flex-col gap-4" data-slot="task-panel" data-kind={kind}>
      {kind === "manual_parse" ? (
        <>
          <Field
            id={`${id}-title`}
            label={t("pipelineTasks.transcript.titleLabel")}
            error={fieldErrorOf(state, RESOLVE_FIELDS.title)}
            className="max-w-2xl"
          >
            <Input
              value={title}
              maxLength={TRANSCRIPT_TITLE_MAX}
              disabled={pending}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          <Field
            id={`${id}-transcript`}
            label={t("pipelineTasks.transcript.label")}
            description={t("pipelineTasks.transcript.help")}
            error={transcriptErrors}
            required
            className="max-w-3xl"
          >
            <Textarea
              value={transcript}
              rows={10}
              spellCheck={false}
              className="font-mono text-xs"
              disabled={pending}
              onChange={(event) => setTranscript(event.target.value)}
            />
          </Field>
          {counts === null || transcript.trim() === "" ? null : (
            <p className="text-sm text-fg-muted" data-slot="transcript-counts" aria-live="polite">
              {t("pipelineTasks.transcript.counts", {
                headings: counts.headings,
                paragraphs: counts.paragraphs,
                tables: counts.tables,
                clauses: counts.clauses,
              })}
            </p>
          )}
        </>
      ) : (
        <>
          <div className="flex flex-col gap-3">
            <p id={`${id}-relevance`} className="text-sm font-medium text-fg">
              {t("pipelineTasks.triage.legend")}
            </p>
            <RadioGroup
              value={relevance}
              onValueChange={(value) => setRelevance(value as "relevant" | "irrelevant")}
              aria-labelledby={`${id}-relevance`}
              disabled={pending}
            >
              {(["relevant", "irrelevant"] as const).map((value) => (
                <div key={value} className="flex items-start gap-2">
                  <RadioGroupItem value={value} id={`${id}-${value}`} className="mt-0.5" />
                  <div className="flex flex-col gap-0.5">
                    <Label htmlFor={`${id}-${value}`}>
                      {value === "relevant"
                        ? t("pipelineTasks.triage.relevant")
                        : t("pipelineTasks.triage.irrelevant")}
                    </Label>
                    <p className="text-xs text-fg-muted">
                      {value === "relevant"
                        ? t("pipelineTasks.triage.relevantHelp")
                        : t("pipelineTasks.triage.irrelevantHelp")}
                    </p>
                  </div>
                </div>
              ))}
            </RadioGroup>
            {fieldErrorOf(state, RESOLVE_FIELDS.relevance) === undefined ? null : (
              <p role="alert" className="text-sm text-danger">
                {fieldErrorOf(state, RESOLVE_FIELDS.relevance)}
              </p>
            )}
          </div>
          {relevance === "relevant" ? (
            <Field
              id={`${id}-type`}
              label={t("pipelineTasks.triage.type")}
              description={t("pipelineTasks.triage.typeHelp")}
              error={fieldErrorOf(state, RESOLVE_FIELDS.docType)}
              required
              className="max-w-md"
            >
              <Select
                value={type}
                disabled={pending}
                placeholder={t("pipelineTasks.triage.typePlaceholder")}
                onChange={(event) => setType(event.target.value)}
                options={TYPES.map((value) => ({ value, label: t(DOCUMENT_TYPE_LABELS[value]) }))}
              />
            </Field>
          ) : null}
        </>
      )}
      <Field
        id={`${id}-reason`}
        label={t("adminPipeline.reason")}
        description={t("adminPipeline.reasonHelp", { min: REASON_MIN_LENGTH })}
        error={fieldErrorOf(state, RESOLVE_FIELDS.reason)}
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
      <div className="flex flex-wrap gap-3">
        <Button
          type="button"
          disabled={!ready || pending}
          aria-busy={pending || undefined}
          onClick={() => setConfirming("resolve")}
        >
          {kind === "manual_parse"
            ? t("pipelineTasks.resolve.transcriptSubmit")
            : t("pipelineTasks.resolve.triageSubmit")}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={pending}
          aria-busy={pending || undefined}
          onClick={() => setConfirming("dismiss")}
        >
          {t("pipelineTasks.dismiss.button")}
        </Button>
      </div>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="task-outcome"
        fieldNames={FIELD_NAMES}
        resendable={isResendable}
      />
      {confirming === "resolve" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(null);
          }}
          title={t("pipelineTasks.resolve.confirmTitle", { title: documentTitle })}
          description={
            kind === "manual_parse"
              ? t("pipelineTasks.resolve.confirmTranscript", { clauses: counts?.clauses ?? 0 })
              : relevance === "irrelevant"
                ? t("pipelineTasks.resolve.confirmIrrelevant")
                : EXTRACTED_TYPES.includes(type)
                  ? t("pipelineTasks.resolve.confirmExtract", { type: typeLabel })
                  : t("pipelineTasks.resolve.confirmReference", { type: typeLabel })
          }
          confirmLabel={
            kind === "manual_parse"
              ? t("pipelineTasks.resolve.transcriptSubmit")
              : t("pipelineTasks.resolve.triageSubmit")
          }
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={sendResolution}
        />
      ) : null}
      {confirming === "dismiss" ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(null);
          }}
          title={t("pipelineTasks.dismiss.dialogTitle", { title: documentTitle })}
          description={
            kind === "manual_parse"
              ? t("pipelineTasks.dismiss.dialogManualParse")
              : t("pipelineTasks.dismiss.dialogTriage")
          }
          label={t("adminPipeline.reason")}
          hint={t("adminPipeline.reasonHelp", { min: REASON_MIN_LENGTH })}
          confirmLabel={t("pipelineTasks.dismiss.button")}
          cancelLabel={t("common.cancel")}
          destructive
          pending={pending}
          onConfirm={(text) => {
            const formData = new FormData();
            formData.set(INTENT, "dismiss");
            formData.set(DISMISS_FIELDS.reason, text);
            setConfirming(null);
            send(formData);
          }}
        />
      ) : null}
    </div>
  );
}
