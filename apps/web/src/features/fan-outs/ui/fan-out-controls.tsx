"use client";

import { useId, useState } from "react";
import { Button, ConfirmDialog, Field, ReasonDialog, Textarea } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { ControlOutcome } from "./control-outcome";
import { CONTROL_FIELDS, REASON_MAX_LENGTH, type FanOutControl } from "./controls-shared";
import { useControl, type ControlAction } from "./use-control";

export interface FanOutControlsProps {
  /** The controls the run's status allows. */
  controls: readonly FanOutControl[];
  /** Only an admin controls a run. */
  canControl: boolean;
  /** "example_rule v2", for the dialogs' titles. */
  name: string;
  action: ControlAction;
}

const LABEL: Readonly<Record<FanOutControl, MessageKey>> = {
  pause: "fanOut.control.pause",
  resume: "fanOut.control.resume",
  cancel: "fanOut.control.cancel",
};

const TITLE: Readonly<Record<FanOutControl, MessageKey>> = {
  pause: "fanOut.control.pauseTitle",
  resume: "fanOut.control.resumeTitle",
  cancel: "fanOut.control.cancelTitle",
};

const DESCRIPTION: Readonly<Record<FanOutControl, MessageKey>> = {
  pause: "fanOut.control.pauseDescription",
  resume: "fanOut.control.resumeDescription",
  cancel: "fanOut.control.cancelDescription",
};

/**
 * Pause, resume or cancel one run, as its status allows. Pausing and cancelling ask for the reason
 * the engine keeps (ReasonDialog, ten characters or more); resuming takes one if given. Cancelling
 * is destructive: the run stops for good and the decisions it made stay, which the dialog says.
 */
export function FanOutControls({ controls, canControl, name, action }: FanOutControlsProps) {
  const id = useId();
  const [open, setOpen] = useState<FanOutControl | null>(null);
  const [note, setNote] = useState("");
  const { attempt, send, pending, outcomeRef } = useControl(action);
  const close = () => {
    setOpen(null);
    setNote("");
  };
  const dispatch = (control: FanOutControl, reason: string) => {
    close();
    send(control, { [CONTROL_FIELDS.control]: control, [CONTROL_FIELDS.reason]: reason });
  };
  if (!canControl) {
    return (
      <p className="text-sm text-fg-muted" data-slot="controls-admin-only">
        {t("fanOut.control.adminOnly")}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3" data-slot="fan-out-controls">
      {controls.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("fanOut.control.none")}</p>
      ) : (
        <ul className="flex flex-wrap gap-3">
          {controls.map((control) => (
            <li key={control} data-control={control}>
              <Button
                type="button"
                variant={
                  control === "cancel" ? "danger" : control === "pause" ? "secondary" : "primary"
                }
                disabled={pending}
                aria-busy={(pending && attempt.sent === control) || undefined}
                onClick={() => {
                  setNote("");
                  setOpen(control);
                }}
              >
                {t(LABEL[control])}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ControlOutcome attempt={attempt} outcomeRef={outcomeRef} slot="control-outcome" />
      {open === "pause" || open === "cancel" ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) close();
          }}
          title={t(TITLE[open], { name })}
          description={t(DESCRIPTION[open])}
          label={t("fanOuts.reason")}
          confirmLabel={t(LABEL[open])}
          cancelLabel={t("common.cancel")}
          destructive={open === "cancel"}
          pending={pending}
          onConfirm={(reason) => dispatch(open, reason)}
        />
      ) : null}
      {open === "resume" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) close();
          }}
          title={t(TITLE.resume, { name })}
          description={t(DESCRIPTION.resume)}
          confirmLabel={t(LABEL.resume)}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={() => dispatch("resume", note.trim())}
        >
          <Field
            id={`${id}-resume-note`}
            label={t("fanOut.control.resumeNote")}
            description={t("fanOut.control.resumeNoteHelp", { max: REASON_MAX_LENGTH })}
          >
            <Textarea
              value={note}
              maxLength={REASON_MAX_LENGTH}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
