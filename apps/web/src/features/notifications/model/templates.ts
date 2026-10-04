import type { Tone } from "@compliancewatch/ui";
import type { MessageTemplate } from "@/entities/notification/types";
import { humanise } from "@/shared/lib/humanise";
import { languageName } from "@/shared/lib/languages";
import { channelLabel } from "./notifications";

/**
 * The template console's rows: every message template the notification service holds, by key,
 * then channel, then language, with its Meta approval status as the service records it (every
 * template is a draft until it is submitted from the Meta business account).
 */
const STATUS_TONE: Readonly<Record<string, Tone>> = {
  approved: "success",
  submitted: "info",
  draft: "neutral",
};

export interface TemplateRow {
  key: string;
  channel: string;
  channelLabel: string;
  language: string;
  languageLabel: string;
  metaName: string;
  status: string;
  statusLabel: string;
  tone: Tone;
  placeholders: readonly string[];
  body: string;
}

export function templateRows(templates: readonly MessageTemplate[]): TemplateRow[] {
  return [...templates]
    .sort(
      (a, b) =>
        a.key.localeCompare(b.key) ||
        a.channel.localeCompare(b.channel) ||
        a.language.localeCompare(b.language),
    )
    .map((template) => ({
      key: template.key,
      channel: template.channel,
      channelLabel: channelLabel(template.channel),
      language: template.language,
      languageLabel: languageName(template.language),
      metaName: template.metaName,
      status: template.status,
      statusLabel: humanise(template.status),
      tone: STATUS_TONE[template.status] ?? "neutral",
      placeholders: template.placeholders,
      body: template.body,
    }));
}

/** How many templates there are, and how many keys they cover. */
export function templateCounts(rows: readonly TemplateRow[]): { templates: number; keys: number } {
  return { templates: rows.length, keys: new Set(rows.map((row) => row.key)).size };
}
