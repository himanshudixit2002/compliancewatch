"use client";

import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import {
  Button,
  ConfirmDialog,
  ErrorState,
  Field,
  Label,
  RadioGroup,
  RadioGroupItem,
  Textarea,
} from "@compliancewatch/ui";
import type { Resolution } from "@/entities/applicability/types";
import { t, type MessageKey } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import { NOTE_MAX_LENGTH, RESOLVE_FIELDS, type ResolveResult } from "./resolve-shared";

export type ResolveAction = (
  state: ActionState<ResolveResult>,
  formData: FormData,
) => Promise<ActionState<ResolveResult>>;

export interface ResolvePanelProps {
  /** The resolve action, bound to the tenant and the item. */
  action: ResolveAction;
  /** "example_rule v2", for the dialog. */
  versionName: string;
}

const OPTIONS: readonly { value: Resolution; label: MessageKey; help: MessageKey }[] = [
  {
    value: "applies",
    label: "decisions.resolution.applies",
    help: "decisions.resolve.appliesHelp",
  },
  {
    value: "not_applicable",
    label: "decisions.resolution.not_applicable",
    help: "decisions.resolve.notApplicableHelp",
  },
  {
    value: "dismiss",
    label: "decisions.resolution.dismiss",
    help: "decisions.resolve.dismissHelp",
  },
];

const CONFIRM: Readonly<Record<Resolution, MessageKey>> = {
  applies: "decisions.resolve.confirmApplies",
  not_applicable: "decisions.resolve.confirmNotApplicable",
  dismiss: "decisions.resolve.confirmDismiss",
};

/**
 * Settling an open item: the reviewer's result (it applies, it does not apply, or dismiss it with
 * no decision) and the note the engine keeps with the item and in its audit log, confirmed in a
 * dialog that says what the engine and the obligation service will do. The reviewer is the
 * signed-in user; the form names nobody.
 */
export function ResolvePanel({ action, versionName }: ResolvePanelProps) {
  const id = useId();
  const [resolution, setResolution] = useState<Resolution | "">("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [state, dispatch, pending] = useActionState(
    async (_previous: ActionState<ResolveResult>, formData: FormData) =>
      action(idleAction(), formData),
    idleAction<ResolveResult>(),
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  const [sent, setSent] = useState(0);
  useEffect(() => {
    if (sent > 0 && !pending) outcomeRef.current?.focus();
  }, [sent, pending]);
  const ready = resolution !== "" && note.trim().length > 0;
  const send = () => {
    if (resolution === "") return;
    const formData = new FormData();
    formData.set(RESOLVE_FIELDS.resolution, resolution);
    formData.set(RESOLVE_FIELDS.note, note.trim());
    setConfirming(false);
    setSent((count) => count + 1);
    startTransition(() => dispatch(formData));
  };
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  return (
    <div className="flex flex-col gap-4" data-slot="resolve-panel">
      <div className="flex flex-col gap-3">
        <p id={`${id}-legend`} className="text-sm font-medium text-fg">
          {t("decisions.resolve.legend")}
        </p>
        <RadioGroup
          value={resolution}
          onValueChange={(value) => setResolution(value as Resolution)}
          aria-labelledby={`${id}-legend`}
        >
          {OPTIONS.map((option) => (
            <div key={option.value} className="flex items-start gap-2">
              <RadioGroupItem
                value={option.value}
                id={`${id}-${option.value}`}
                className="mt-0.5"
              />
              <div className="flex flex-col gap-0.5">
                <Label htmlFor={`${id}-${option.value}`}>{t(option.label)}</Label>
                <p className="text-xs text-fg-muted">{t(option.help)}</p>
              </div>
            </div>
          ))}
        </RadioGroup>
        {fieldErrorOf(state, RESOLVE_FIELDS.resolution) === undefined ? null : (
          <p role="alert" className="text-sm text-danger">
            {fieldErrorOf(state, RESOLVE_FIELDS.resolution)}
          </p>
        )}
      </div>
      <Field
        id={`${id}-note`}
        label={t("decisions.resolve.note")}
        description={t("decisions.resolve.noteHelp", { max: NOTE_MAX_LENGTH })}
        error={fieldErrorOf(state, RESOLVE_FIELDS.note)}
        required
      >
        <Textarea
          value={note}
          maxLength={NOTE_MAX_LENGTH}
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>
      <div>
        <Button
          type="button"
          disabled={!ready || pending}
          aria-busy={pending || undefined}
          onClick={() => setConfirming(true)}
        >
          {t("decisions.resolve.submit")}
        </Button>
      </div>
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="resolve-outcome"
        className="flex flex-col gap-2 outline-none"
      >
        {state.status === "ok" ? (
          <p role="status" className="text-sm font-medium text-fg" data-slot="resolve-done">
            {state.value?.message ?? state.message ?? ""}
          </p>
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
      {confirming && resolution !== "" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("decisions.resolve.dialogTitle", { name: versionName })}
          description={t(CONFIRM[resolution])}
          confirmLabel={t("decisions.resolve.submit")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={send}
        />
      ) : null}
    </div>
  );
}
