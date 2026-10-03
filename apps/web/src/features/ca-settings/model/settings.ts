import { t } from "@/shared/i18n";

export interface ApiKey {
  id: string;
  name: string;
  keyPrefix: string;
  createdAt: string;
  lastUsed: string | null;
  active: boolean;
}

export interface DigestConfig {
  id: string;
  frequency: "daily" | "weekly" | "monthly";
  time: string;
  timezone: string;
  active: boolean;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  createdAt: string;
  lastTriggered: string | null;
}

export interface CaSettingsView {
  apiKeys: ApiKey[];
  digests: DigestConfig[];
  webhooks: Webhook[];
}

export function emptyCaSettings(): CaSettingsView {
  return {
    apiKeys: [],
    digests: [],
    webhooks: [],
  };
}

export function apiKeyStatusLabel(active: boolean): string {
  return active ? t("caSettings.apiKey.status.active") : t("caSettings.apiKey.status.revoked");
}

export function apiKeyStatusTone(active: boolean): "success" | "neutral" | "danger" {
  if (active) return "success";
  return "danger";
}

export function webhookEventLabel(event: string): string {
  return t(`caSettings.webhook.event.${event}`, event);
}

export const DIGEST_FREQUENCIES: { value: DigestConfig["frequency"]; label: string }[] = [
  { value: "daily", label: t("caSettings.digest.frequency.daily") },
  { value: "weekly", label: t("caSettings.digest.frequency.weekly") },
  { value: "monthly", label: t("caSettings.digest.frequency.monthly") },
];

export const COMMON_TIMEZONES: { value: string; label: string }[] = [
  { value: "Asia/Kolkata", label: "India (IST)" },
  { value: "America/New_York", label: "US Eastern (ET)" },
  { value: "America/Los_Angeles", label: "US Pacific (PT)" },
  { value: "Europe/London", label: "UK (GMT/BST)" },
  { value: "Europe/Paris", label: "Central Europe (CET)" },
  { value: "Asia/Dubai", label: "Gulf (GST)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Australia/Sydney", label: "Australia East (AEST)" },
];
