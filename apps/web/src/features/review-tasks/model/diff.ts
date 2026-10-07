import {
  obligationTemplateFromMapping,
  recurrenceFromMapping,
  specificationFromMapping,
} from "@/entities/rule-version/mappers";
import type {
  ObligationTemplate,
  ProposedDraft,
  Recurrence,
  RuleVersion,
  SpecNode,
} from "@/entities/rule-version/types";
import type { Ontology } from "@/entities/ontology/types";
import { t, type MessageKey } from "@/shared/i18n";
import { diffLines, hasChanges, type DiffLine } from "@/shared/lib/diff";
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { describeSpecification, specificationText } from "@/shared/ui/specification";
import { dueInDaysWords, recurrenceWords } from "./content";

/**
 * Two drafts compared field by field, each field as lines of words (the condition as the lines it
 * reads in, the steps and questions one per line), with `shared/lib/diff.ts`: the candidate's
 * proposal against the draft an analyst made of it, and the rule's previous version against this
 * draft. A field one side does not state (a proposal states no questions) is left out.
 */
export interface ComparableContent {
  title: string | null;
  summary: string | null;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  recurrence: Recurrence | null;
  template: ObligationTemplate | null;
  /** Null when this side states no questions (a candidate's proposal). */
  todo: readonly string[] | null;
  /** Null when the side states no condition. */
  specification: SpecNode | null;
}

export function versionContent(version: RuleVersion): ComparableContent {
  return {
    title: version.title,
    summary: version.summary,
    effectiveFrom: version.effectiveFrom,
    effectiveTo: version.effectiveTo,
    recurrence: version.recurrence,
    template: version.obligationTemplate,
    todo: version.todo,
    specification: version.specification,
  };
}

export function proposalContent(proposed: ProposedDraft): ComparableContent {
  return {
    title: proposed.title,
    summary: proposed.summary,
    effectiveFrom: proposed.effectiveFrom,
    effectiveTo: proposed.effectiveTo,
    recurrence: recurrenceFromMapping(proposed.recurrence),
    template: obligationTemplateFromMapping(proposed.obligationTemplate),
    todo: null,
    specification:
      proposed.specification === null ? null : specificationFromMapping(proposed.specification),
  };
}

type Field = "title" | "summary" | "period" | "recurrence" | "template" | "todo" | "specification";

const FIELD_LABELS: Readonly<Record<Field, MessageKey>> = {
  title: "workbench.diff.field.title",
  summary: "workbench.diff.field.summary",
  period: "workbench.diff.field.period",
  recurrence: "workbench.diff.field.recurrence",
  template: "workbench.diff.field.template",
  todo: "workbench.diff.field.todo",
  specification: "workbench.diff.field.specification",
};

const FIELDS: readonly Field[] = [
  "title",
  "summary",
  "period",
  "recurrence",
  "template",
  "todo",
  "specification",
];

/** A summary a sentence a line, so a changed sentence shows as one. */
function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

function templateLines(template: ObligationTemplate | null): string[] {
  if (template === null) return [t("workbench.diff.notStated")];
  return [
    template.title,
    ...template.steps.map((step, index) => t("workbench.diff.step", { n: index + 1, step })),
    dueInDaysWords(template),
    t("workbench.diff.evidence", {
      evidence:
        template.evidenceType === null || template.evidenceType === ""
          ? t("common.none")
          : humanise(template.evidenceType),
    }),
  ];
}

/** The lines a field reads as; null when the side does not state the field at all. */
function fieldLines(
  content: ComparableContent,
  field: Field,
  ontology: Ontology | null,
): string[] | null {
  switch (field) {
    case "title":
      return content.title === null ? [t("workbench.diff.notStated")] : [content.title];
    case "summary":
      return content.summary === null
        ? [t("workbench.diff.notStated")]
        : sentences(content.summary);
    case "period":
      return [
        t("workbench.diff.from", {
          date:
            content.effectiveFrom === null
              ? t("workbench.diff.notStated")
              : formatDate(content.effectiveFrom),
        }),
        t("workbench.diff.to", {
          date:
            content.effectiveTo === null
              ? t("workbench.diff.openEnded")
              : formatDate(content.effectiveTo),
        }),
      ];
    case "recurrence":
      return [recurrenceWords(content.recurrence)];
    case "template":
      return templateLines(content.template);
    case "todo":
      return content.todo === null ? null : [...content.todo];
    case "specification":
      return content.specification === null
        ? [t("workbench.diff.notStated")]
        : specificationText(describeSpecification(content.specification, ontology));
  }
}

export interface FieldDiff {
  field: Field;
  label: string;
  lines: DiffLine[];
}

export interface Comparison {
  /** What is compared, "The candidate's proposal and the draft". */
  title: string;
  beforeLabel: string;
  afterLabel: string;
  /** The fields that differ, each with its lines. */
  changed: FieldDiff[];
  /** The labels of the fields that read the same on both sides. */
  same: string[];
}

export function compare(
  before: ComparableContent,
  after: ComparableContent,
  ontology: Ontology | null,
  words: { title: string; beforeLabel: string; afterLabel: string },
): Comparison {
  const changed: FieldDiff[] = [];
  const same: string[] = [];
  for (const field of FIELDS) {
    const left = fieldLines(before, field, ontology);
    const right = fieldLines(after, field, ontology);
    if (left === null || right === null) continue;
    const lines = diffLines(left, right);
    const label = t(FIELD_LABELS[field]);
    if (hasChanges(lines)) changed.push({ field, label, lines });
    else same.push(label);
  }
  return { ...words, changed, same };
}
