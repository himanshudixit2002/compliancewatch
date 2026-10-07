import {
  obligationTemplateFromMapping,
  recurrenceFromMapping,
} from "@/entities/rule-version/mappers";
import {
  FREQUENCIES,
  type ObligationTemplate,
  type ProposedDraft,
  type Recurrence,
  type RuleVersion,
} from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import type { ContentValues, Frequency } from "../ui/form-shared";

/**
 * A draft's content in the two forms the workbench needs: the values its inputs start from (a
 * version's stored content to edit, or the draft a candidate proposes), and the words a pane shows
 * for the duty it creates and how it recurs. The kernel's mappings are read with the rule
 * version entity's mappers; a mapping of an unknown shape reads as missing rather than guessed.
 */
function isFrequency(value: string): value is Frequency {
  return (FREQUENCIES as readonly string[]).includes(value);
}

function numberText(value: number | null): string {
  return value === null ? "" : String(value);
}

function recurrenceValues(
  recurrence: Recurrence | null,
): Pick<ContentValues, "frequency" | "dueDay" | "dueMonthOffset"> {
  if (recurrence === null || !isFrequency(recurrence.frequency)) {
    return { frequency: "", dueDay: "", dueMonthOffset: "" };
  }
  return {
    frequency: recurrence.frequency,
    dueDay: numberText(recurrence.dueDay),
    dueMonthOffset: numberText(recurrence.dueMonthOffset ?? 0),
  };
}

function templateValues(
  template: ObligationTemplate | null,
): Pick<
  ContentValues,
  "templateTitle" | "templateSteps" | "templateDueInDays" | "templateEvidence"
> {
  return {
    templateTitle: template?.title ?? "",
    templateSteps: (template?.steps ?? []).join("\n"),
    templateDueInDays: numberText(template?.dueInDays ?? null),
    templateEvidence: template?.evidenceType ?? "",
  };
}

/** The edit form's starting values: the draft as stored. */
export function versionValues(version: RuleVersion): ContentValues {
  return {
    title: version.title,
    summary: version.summary,
    effectiveFrom: version.effectiveFrom,
    effectiveTo: version.effectiveTo ?? "",
    ...recurrenceValues(version.recurrence),
    ...templateValues(version.obligationTemplate),
    todo: version.todo.join("\n"),
    specification: version.stored.specification,
  };
}

/**
 * The draft form's starting values: what the candidate proposes, each field it does not map left
 * empty for the analyst to fill (the proposal's `problems` say why it is empty).
 */
export function proposalValues(proposed: ProposedDraft): ContentValues {
  return {
    title: proposed.title ?? "",
    summary: proposed.summary ?? "",
    effectiveFrom: proposed.effectiveFrom ?? "",
    effectiveTo: proposed.effectiveTo ?? "",
    ...recurrenceValues(recurrenceFromMapping(proposed.recurrence)),
    ...templateValues(obligationTemplateFromMapping(proposed.obligationTemplate)),
    todo: "",
    specification: proposed.specification,
  };
}

const FREQUENCY_LABELS: Readonly<Record<Frequency, MessageKey>> = {
  monthly: "workbench.frequency.monthly",
  quarterly: "workbench.frequency.quarterly",
  half_yearly: "workbench.frequency.half_yearly",
  annual: "workbench.frequency.annual",
};

export function frequencyLabel(frequency: string): string {
  return isFrequency(frequency) ? t(FREQUENCY_LABELS[frequency]) : humanise(frequency);
}

/**
 * How a duty recurs, in words: "Monthly, due on day 20 of the month after the period". The
 * kernel's month offset counts from that month (0 is the month that follows the period).
 */
export function recurrenceWords(recurrence: Recurrence | null): string {
  if (recurrence === null) return t("workbench.recurrence.none");
  const offset = recurrence.dueMonthOffset ?? 0;
  const words = {
    frequency: frequencyLabel(recurrence.frequency),
    day: recurrence.dueDay ?? "-",
    offset,
  };
  return offset === 0
    ? t("workbench.recurrence.words", words)
    : t("workbench.recurrence.wordsLater", words);
}

/** When a one-off duty falls due, in words. */
export function dueInDaysWords(template: ObligationTemplate | null): string {
  if (template === null || template.dueInDays === null) return t("workbench.dueInDays.none");
  return t("workbench.dueInDays.words", { days: template.dueInDays });
}

/** An effective period in words: "From 1 Apr 2000, open-ended". */
export function periodWords(from: string | null, to: string | null): string {
  const start = from === null || from === "" ? t("workbench.period.noStart") : formatDate(from);
  return to === null || to === ""
    ? t("workbench.period.openEnded", { from: start })
    : t("workbench.period.bounded", { from: start, to: formatDate(to) });
}
