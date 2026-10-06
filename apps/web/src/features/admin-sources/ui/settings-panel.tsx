"use client";

import { useId, useState } from "react";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Field,
  Input,
  Label,
  Textarea,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, type ActionState } from "@/shared/lib/action-state";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import {
  CADENCE_MAX_SECONDS,
  CADENCE_MIN_SECONDS,
  CHECKED,
  NAME_MAX_LENGTH,
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  SETTINGS_FIELDS,
  type SettingsDefaults,
  type SettingsResult,
} from "./source-shared";

export interface SettingsPanelProps {
  /** The settings action, bound to the source. */
  action: WriteAction<SettingsResult>;
  defaults: SettingsDefaults;
  /** Upload-only sources are never crawled: their cadence and switches change nothing yet. */
  listable: boolean;
}

const FIELD_NAMES = Object.values(SETTINGS_FIELDS);

/**
 * An admin's change of a source's settings: its name, cadence, the enabled and paused switches,
 * and its adapter type's parameters (all of them, as JSON; the pipeline checks them again), with
 * the reason the pipeline keeps in its audit entry. Only the settings that differ from the source
 * as the pipeline holds it are sent; a dialog says what is recorded before anything is.
 */
export function SettingsPanel({ action, defaults, listable }: SettingsPanelProps) {
  const id = useId();
  const [name, setName] = useState(defaults.name);
  const [cadence, setCadence] = useState(String(defaults.cadenceSeconds));
  const [enabled, setEnabled] = useState(defaults.enabled);
  const [paused, setPaused] = useState(defaults.paused);
  const [parameters, setParameters] = useState(defaults.parameters);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  const state: ActionState<SettingsResult> = attempt.last;

  const submit = () => {
    const formData = new FormData();
    formData.set(SETTINGS_FIELDS.name, name);
    formData.set(SETTINGS_FIELDS.cadence, cadence.trim());
    if (enabled) formData.set(SETTINGS_FIELDS.enabled, CHECKED);
    if (paused) formData.set(SETTINGS_FIELDS.paused, CHECKED);
    formData.set(SETTINGS_FIELDS.parameters, parameters);
    formData.set(SETTINGS_FIELDS.reason, reason.trim());
    setConfirming(false);
    send(formData);
  };

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="settings-panel"
      className="flex flex-col gap-4"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("adminSources.settings.title")}
      </h2>
      <p className="max-w-prose text-sm text-fg-muted">
        {listable ? t("adminSources.settings.intro") : t("adminSources.settings.introUploadOnly")}
      </p>
      <Field
        id={`${id}-name`}
        label={t("adminSources.settings.name")}
        error={fieldErrorOf(state, SETTINGS_FIELDS.name)}
        required
        className="max-w-md"
      >
        <Input
          value={name}
          maxLength={NAME_MAX_LENGTH}
          disabled={pending}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      <Field
        id={`${id}-cadence`}
        label={t("adminSources.settings.cadence")}
        description={t("adminSources.settings.cadenceHelp", {
          min: CADENCE_MIN_SECONDS,
          max: CADENCE_MAX_SECONDS,
        })}
        error={fieldErrorOf(state, SETTINGS_FIELDS.cadence)}
        required
        className="max-w-xs"
      >
        <Input
          value={cadence}
          inputMode="numeric"
          disabled={pending}
          onChange={(event) => setCadence(event.target.value)}
        />
      </Field>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${id}-enabled`}
            checked={enabled}
            disabled={pending}
            onCheckedChange={(value) => setEnabled(value === true)}
          />
          <Label htmlFor={`${id}-enabled`}>{t("adminSources.settings.enabledLabel")}</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${id}-paused`}
            checked={paused}
            disabled={pending}
            onCheckedChange={(value) => setPaused(value === true)}
          />
          <Label htmlFor={`${id}-paused`}>{t("adminSources.settings.pausedLabel")}</Label>
        </div>
      </div>
      <Field
        id={`${id}-parameters`}
        label={t("adminSources.settings.parameters")}
        description={t("adminSources.settings.parametersHelp")}
        error={fieldErrorOf(state, SETTINGS_FIELDS.parameters)}
        className="max-w-2xl"
      >
        <Textarea
          value={parameters}
          rows={5}
          spellCheck={false}
          className="font-mono text-xs"
          disabled={pending}
          onChange={(event) => setParameters(event.target.value)}
        />
      </Field>
      <Field
        id={`${id}-reason`}
        label={t("adminSources.reason")}
        description={t("adminSources.reasonHelp", { min: REASON_MIN_LENGTH })}
        error={fieldErrorOf(state, SETTINGS_FIELDS.reason)}
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
          {t("adminSources.settings.save")}
        </Button>
      </div>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="settings-outcome"
        fieldNames={FIELD_NAMES}
      />
      {confirming ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("adminSources.settings.confirmTitle")}
          description={t("adminSources.settings.confirmBody")}
          confirmLabel={t("adminSources.settings.save")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={submit}
        />
      ) : null}
    </section>
  );
}
