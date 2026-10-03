"use client";

import { useId, useState } from "react";
import {
  Banner,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Label,
  PageHeader,
  Select,
  type SelectOption,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { COMMON_TIMEZONES, DIGEST_FREQUENCIES, type DigestConfig } from "../model/settings";

export interface DigestsViewProps {
  title: string;
  config: DigestConfig | null;
  onSave?: (config: DigestConfig) => void | Promise<void>;
}

interface DigestFormValues {
  frequency: DigestConfig["frequency"];
  time: string;
  timezone: string;
  active: boolean;
}

const EMPTY_FORM: DigestFormValues = {
  frequency: "weekly",
  time: "09:00",
  timezone: "Asia/Kolkata",
  active: true,
};

const FREQUENCY_OPTIONS: SelectOption[] = DIGEST_FREQUENCIES.map((option) => ({
  value: option.value,
  label: option.label,
}));

const TIMEZONE_OPTIONS: SelectOption[] = COMMON_TIMEZONES.map((option) => ({
  value: option.value,
  label: option.label,
}));

export function DigestsView({ title, config, onSave }: DigestsViewProps) {
  const id = useId();
  const frequencyId = `${id}-frequency`;
  const timeId = `${id}-time`;
  const timezoneId = `${id}-timezone`;
  const activeId = `${id}-active`;

  const initial: DigestFormValues = config
    ? {
        frequency: config.frequency,
        time: config.time,
        timezone: config.timezone,
        active: config.active,
      }
    : EMPTY_FORM;

  const [values, setValues] = useState<DigestFormValues>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!onSave) return;
    setSaving(true);
    setSaved(false);
    try {
      const next: DigestConfig = {
        id: config?.id ?? "digest-default",
        frequency: values.frequency,
        time: values.time,
        timezone: values.timezone,
        active: values.active,
      };
      await onSave(next);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-slot="ca-digests" className="flex max-w-2xl flex-col gap-6">
      <PageHeader title={title} description={t("caSettings.digest.intro")} />

      <Card>
        <CardHeader>
          <CardTitle>{t("caSettings.digest.cardTitle")}</CardTitle>
          <CardDescription>{t("caSettings.digest.cardDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={handleSave}
            className="flex flex-col gap-4"
            data-slot="digest-form"
            aria-label={t("caSettings.digest.formLabel")}
          >
            <Field id={frequencyId} label={t("caSettings.digest.frequency")}>
              <Select
                id={frequencyId}
                value={values.frequency}
                onChange={(event: React.ChangeEvent<HTMLSelectElement>) =>
                  setValues({
                    ...values,
                    frequency: event.target.value as DigestConfig["frequency"],
                  })
                }
                options={FREQUENCY_OPTIONS}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id={timeId}
                label={t("caSettings.digest.time")}
                description={t("caSettings.digest.timeHelp")}
              >
                <Input
                  id={timeId}
                  type="time"
                  value={values.time}
                  onChange={(event) => setValues({ ...values, time: event.target.value })}
                  required
                />
              </Field>
              <Field id={timezoneId} label={t("caSettings.digest.timezone")}>
                <Select
                  id={timezoneId}
                  value={values.timezone}
                  onChange={(event: React.ChangeEvent<HTMLSelectElement>) =>
                    setValues({ ...values, timezone: event.target.value })
                  }
                  options={TIMEZONE_OPTIONS}
                />
              </Field>
            </div>

            <div className="flex items-center gap-2">
              <input
                id={activeId}
                type="checkbox"
                checked={values.active}
                onChange={(event) => setValues({ ...values, active: event.target.checked })}
                className="h-4 w-4 rounded border-line text-primary focus:ring-focus/50"
              />
              <Label htmlFor={activeId}>{t("caSettings.digest.active")}</Label>
            </div>

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={saving} aria-busy={saving || undefined}>
                {saving ? t("caSettings.digest.saving") : t("caSettings.digest.save")}
              </Button>
              {saved ? <Banner tone="success" title={t("caSettings.digest.saved")} /> : null}
            </div>
          </form>
        </CardContent>
      </Card>

      {config === null ? (
        <Banner tone="info" title={t("caSettings.digest.noConfig")}>
          <p>{t("caSettings.digest.noConfigDescription")}</p>
        </Banner>
      ) : null}
    </div>
  );
}
