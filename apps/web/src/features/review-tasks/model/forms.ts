import {
  FREQUENCIES,
  RULE_REJECT_REASONS,
  type CitationInput,
  type DraftEdit,
  type DraftFields,
  type DraftFromCandidate,
  type ReviewDecision,
  type RuleRejectReason,
  type TaskDecisionInput,
  type VersionLevel,
} from "@/entities/rule-version/types";
import { t } from "@/shared/i18n";
import { isDateKey } from "@/shared/lib/dates";
import { isHexUuid } from "@/shared/lib/identifiers";
import {
  BASE_PREFIX,
  CLAIM_FIELD,
  CONTENT_FIELDS,
  DECIDE_FIELDS,
  DRAFT_FIELDS,
  EDITS_PREFIX,
  LIMITS,
  NOTE_FIELD,
  RULE_KEY,
  citationField,
  relationField,
} from "../ui/form-shared";
import { shapeProblem } from "../ui/predicate-tree";

/**
 * The workbench forms' shapes, checked before the rulebook is asked. A content field is sent
 * only when its value differs from the one it was rendered with (`base:<name>`), and only a field
 * that is sent is checked here; the rulebook checks the whole draft against the ontology and the
 * seed calendar's rules and lists every problem it finds. Errors are keyed by the rulebook's body
 * fields, as a 422 from it would be.
 */
export type FormErrors = Record<string, string[]>;

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function lines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** A JSON text with its object keys sorted, so two mappings compare by content alone. */
export function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item !== null && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.entries(item as Record<string, unknown>).sort(([a], [b]) =>
            a < b ? -1 : a > b ? 1 : 0,
          ),
        )
      : item,
  );
}

function wholeNumber(value: string): number | null {
  return /^\d+$/.test(value) ? Number(value) : null;
}

function add(errors: FormErrors, field: string, message: string): void {
  (errors[field] ??= []).push(message);
}

type Read = (name: string) => string;

interface FieldRule<T> {
  /** The form names the field is read from (the first carries its errors). */
  names: readonly string[];
  read: (value: Read) => T;
  /** The problems of a changed value, as [field, message] pairs. */
  check: (value: T, read: Read) => [string, string][];
  set: (fields: DraftFields, value: T) => void;
}

function recurrenceOf(read: Read): Record<string, unknown> | null {
  const frequency = read(CONTENT_FIELDS.frequency).trim();
  if (frequency === "") return null;
  const day = read(CONTENT_FIELDS.dueDay).trim();
  const offset = read(CONTENT_FIELDS.dueMonthOffset).trim();
  return {
    frequency,
    due_day: wholeNumber(day) ?? day,
    due_month_offset: offset === "" ? 0 : (wholeNumber(offset) ?? offset),
  };
}

function templateOf(read: Read): Record<string, unknown> {
  const due = read(CONTENT_FIELDS.templateDueInDays).trim();
  return {
    title: read(CONTENT_FIELDS.templateTitle).trim(),
    steps: lines(read(CONTENT_FIELDS.templateSteps)),
    due_in_days: due === "" ? null : (wholeNumber(due) ?? due),
    evidence_type: read(CONTENT_FIELDS.templateEvidence).trim(),
  };
}

/** A specification field whose text is not JSON, kept as its text so a change still shows. */
class NotJson {
  readonly text: string;

  constructor(text: string) {
    this.text = text;
  }

  toJSON(): string {
    return `not json: ${this.text}`;
  }
}

function specificationOf(read: Read): unknown {
  const raw = read(CONTENT_FIELDS.specification).trim();
  if (raw === "") return {};
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return new NotJson(raw);
  }
}

const RULES: readonly FieldRule<unknown>[] = [
  {
    names: [CONTENT_FIELDS.title],
    read: (value) => value(CONTENT_FIELDS.title).trim(),
    check: (value) => {
      const title = value as string;
      if (title === "") return [[CONTENT_FIELDS.title, t("workbench.error.titleEmpty")]];
      if (title.length > LIMITS.title) {
        return [[CONTENT_FIELDS.title, t("workbench.error.tooLong", { max: LIMITS.title })]];
      }
      return [];
    },
    set: (fields, value) => {
      fields.title = value as string;
    },
  },
  {
    names: [CONTENT_FIELDS.summary],
    read: (value) => value(CONTENT_FIELDS.summary).trim(),
    check: (value) =>
      (value as string).length > LIMITS.summary
        ? [[CONTENT_FIELDS.summary, t("workbench.error.tooLong", { max: LIMITS.summary })]]
        : [],
    set: (fields, value) => {
      fields.summary = value as string;
    },
  },
  {
    names: [CONTENT_FIELDS.effectiveFrom],
    read: (value) => value(CONTENT_FIELDS.effectiveFrom).trim(),
    check: (value) =>
      isDateKey(value as string) ? [] : [[CONTENT_FIELDS.effectiveFrom, t("workbench.error.date")]],
    set: (fields, value) => {
      fields.effectiveFrom = value as string;
    },
  },
  {
    names: [CONTENT_FIELDS.effectiveTo],
    read: (value) => {
      const to = value(CONTENT_FIELDS.effectiveTo).trim();
      return to === "" ? null : to;
    },
    check: (value) =>
      value === null || isDateKey(value as string)
        ? []
        : [[CONTENT_FIELDS.effectiveTo, t("workbench.error.date")]],
    set: (fields, value) => {
      fields.effectiveTo = value as string | null;
    },
  },
  {
    names: [CONTENT_FIELDS.frequency, CONTENT_FIELDS.dueDay, CONTENT_FIELDS.dueMonthOffset],
    read: recurrenceOf,
    check: (value) => {
      if (value === null) return [];
      const recurrence = value as Record<string, unknown>;
      const problems: [string, string][] = [];
      if (!(FREQUENCIES as readonly unknown[]).includes(recurrence.frequency)) {
        problems.push([CONTENT_FIELDS.frequency, t("workbench.error.frequency")]);
      }
      const day = recurrence.due_day;
      if (typeof day !== "number" || day < 1 || day > LIMITS.dueDay) {
        problems.push([CONTENT_FIELDS.dueDay, t("workbench.error.dueDay", { max: LIMITS.dueDay })]);
      }
      const offset = recurrence.due_month_offset;
      if (typeof offset !== "number" || offset > LIMITS.dueMonthOffset) {
        problems.push([
          CONTENT_FIELDS.dueMonthOffset,
          t("workbench.error.dueMonthOffset", { max: LIMITS.dueMonthOffset }),
        ]);
      }
      return problems;
    },
    set: (fields, value) => {
      fields.recurrence = value as Record<string, unknown> | null;
    },
  },
  {
    names: [
      CONTENT_FIELDS.templateTitle,
      CONTENT_FIELDS.templateSteps,
      CONTENT_FIELDS.templateDueInDays,
      CONTENT_FIELDS.templateEvidence,
    ],
    read: templateOf,
    check: (value) => {
      const template = value as Record<string, unknown>;
      const problems: [string, string][] = [];
      if (template.title === "") {
        problems.push([CONTENT_FIELDS.templateTitle, t("workbench.error.templateTitle")]);
      }
      if (template.due_in_days !== null && typeof template.due_in_days !== "number") {
        problems.push([CONTENT_FIELDS.templateDueInDays, t("workbench.error.dueInDays")]);
      }
      return problems;
    },
    set: (fields, value) => {
      fields.obligationTemplate = value as Record<string, unknown>;
    },
  },
  {
    names: [CONTENT_FIELDS.todo],
    read: (value) => lines(value(CONTENT_FIELDS.todo)),
    check: (value) => {
      const questions = value as string[];
      if (questions.length > LIMITS.todo) {
        return [[CONTENT_FIELDS.todo, t("workbench.error.todoCount", { max: LIMITS.todo })]];
      }
      if (questions.some((question) => question.length > LIMITS.question)) {
        return [[CONTENT_FIELDS.todo, t("workbench.error.question", { max: LIMITS.question })]];
      }
      return [];
    },
    set: (fields, value) => {
      fields.todo = value as string[];
    },
  },
  {
    names: [CONTENT_FIELDS.specification],
    read: specificationOf,
    check: (value) => {
      if (value instanceof NotJson) {
        return [[CONTENT_FIELDS.specification, t("predicateEditor.json.syntax")]];
      }
      const problem = shapeProblem(value);
      return problem === null ? [] : [[CONTENT_FIELDS.specification, problem]];
    },
    set: (fields, value) => {
      fields.specification = value as Record<string, unknown>;
    },
  },
];

/**
 * The content fields whose value changed from the one they were rendered with, checked for shape.
 * `prefix` is the forms' name prefix (`edits.` for the draft from a candidate); errors carry it.
 */
export function parseContentChanges(
  formData: FormData,
  prefix = "",
): { fields: DraftFields; changed: number; errors: FormErrors } {
  const current: Read = (name) => text(formData, `${prefix}${name}`);
  const base: Read = (name) => text(formData, `${BASE_PREFIX}${prefix}${name}`);
  const fields: DraftFields = {};
  const errors: FormErrors = {};
  let changed = 0;
  for (const rule of RULES) {
    const value = rule.read(current);
    if (canonical(value) === canonical(rule.read(base))) continue;
    changed += 1;
    const problems = rule.check(value, current);
    for (const [field, message] of problems) add(errors, `${prefix}${field}`, message);
    if (problems.length === 0) rule.set(fields, value);
  }
  return { fields, changed, errors };
}

/**
 * The citation rows: a clause of a cited document by its id and the words of it the rule rests
 * on. A row left blank is skipped; a row with one half is an error on the other.
 */
export function parseCitations(formData: FormData): {
  citations: CitationInput[];
  errors: FormErrors;
} {
  const citations: CitationInput[] = [];
  const errors: FormErrors = {};
  for (let index = 0; index < LIMITS.citations; index += 1) {
    const clauseName = citationField(index, "clause_id");
    const quoteName = citationField(index, "quote");
    if (!formData.has(clauseName) && !formData.has(quoteName)) continue;
    const clauseId = text(formData, clauseName).trim().toLowerCase();
    const quote = text(formData, quoteName).trim();
    if (clauseId === "" && quote === "") continue;
    if (!isHexUuid(clauseId)) add(errors, clauseName, t("workbench.error.clause"));
    if (quote === "") add(errors, quoteName, t("workbench.error.quoteEmpty"));
    else if (quote.length > LIMITS.quote) {
      add(errors, quoteName, t("workbench.error.tooLong", { max: LIMITS.quote }));
    }
    if (isHexUuid(clauseId) && quote !== "" && quote.length <= LIMITS.quote) {
      citations.push({ clauseId, quote });
    }
  }
  return { citations, errors };
}

function noteOf(formData: FormData, errors: FormErrors, required: boolean): string {
  const note = text(formData, NOTE_FIELD).trim();
  if (note.length > LIMITS.note) {
    add(errors, NOTE_FIELD, t("workbench.error.tooLong", { max: LIMITS.note }));
  } else if (required && note === "") {
    add(errors, NOTE_FIELD, t("workbench.error.noteRequired"));
  }
  return note;
}

export type Parsed<T> =
  { ok: true; value: T } | { ok: false; errors: FormErrors; formErrors: string[] };

function failed<T>(errors: FormErrors, formErrors: string[] = []): Parsed<T> {
  return { ok: false, errors, formErrors };
}

/** An edit of a claimed task's draft: the changed fields, the citations added, and why. */
export function parseEdit(formData: FormData): Parsed<DraftEdit> {
  const content = parseContentChanges(formData);
  const cited = parseCitations(formData);
  const errors: FormErrors = { ...content.errors, ...cited.errors };
  const note = noteOf(formData, errors, false);
  if (Object.keys(errors).length > 0) return failed(errors);
  if (content.changed === 0 && cited.citations.length === 0) {
    return failed({}, [t("workbench.edit.nothing")]);
  }
  return { ok: true, value: { fields: content.fields, citations: cited.citations, note } };
}

const LEVELS: readonly VersionLevel[] = ["entity", "registration", "location"];

function isLevel(value: string): value is VersionLevel {
  return (LEVELS as readonly string[]).includes(value);
}

/**
 * A version drafted from the candidate: the rule it joins (or starts, with its regulator and
 * level), the changes to what the candidate proposes, the citations (the candidate's quotes
 * unless the analyst cites others), the relation candidates taken on, and why.
 */
export function parseDraft(
  formData: FormData,
  relationsNeedingTarget: ReadonlySet<string>,
): Parsed<DraftFromCandidate> {
  const errors: FormErrors = {};
  const ruleKey = text(formData, DRAFT_FIELDS.ruleKey).trim();
  if (ruleKey === "") add(errors, DRAFT_FIELDS.ruleKey, t("workbench.error.ruleKeyEmpty"));
  else if (ruleKey.length > LIMITS.ruleKey || !RULE_KEY.test(ruleKey)) {
    add(errors, DRAFT_FIELDS.ruleKey, t("workbench.error.ruleKeyShape"));
  }
  let newRule: DraftFromCandidate["newRule"] = null;
  if (text(formData, DRAFT_FIELDS.newRule) === "on") {
    const regulator = text(formData, DRAFT_FIELDS.regulator).trim();
    const level = text(formData, DRAFT_FIELDS.level);
    if (regulator === "" || regulator.length > LIMITS.regulator) {
      add(
        errors,
        DRAFT_FIELDS.regulator,
        t("workbench.error.regulator", { max: LIMITS.regulator }),
      );
    }
    if (!isLevel(level)) add(errors, DRAFT_FIELDS.level, t("workbench.error.level"));
    if (regulator !== "" && regulator.length <= LIMITS.regulator && isLevel(level)) {
      newRule = { regulator, level };
    }
  }
  const content = parseContentChanges(formData, EDITS_PREFIX);
  Object.assign(errors, content.errors);
  let citations: CitationInput[] | null = null;
  if (text(formData, DRAFT_FIELDS.citationsMode) === "own") {
    const cited = parseCitations(formData);
    Object.assign(errors, cited.errors);
    citations = cited.citations;
  }
  const relations: DraftFromCandidate["relations"][number][] = [];
  for (let index = 0; index < LIMITS.relations; index += 1) {
    const candidateId = text(formData, relationField(index, "candidate_id")).trim().toLowerCase();
    if (candidateId === "") continue;
    const targetName = relationField(index, "target_rule_version_id");
    const target = text(formData, targetName).trim().toLowerCase();
    if (!isHexUuid(candidateId)) continue;
    if (target === "" && relationsNeedingTarget.has(candidateId)) {
      add(errors, targetName, t("workbench.error.relationTarget"));
      continue;
    }
    if (target !== "" && !isHexUuid(target)) {
      add(errors, targetName, t("workbench.error.relationTarget"));
      continue;
    }
    relations.push({ candidateId, targetRuleVersionId: target === "" ? null : target });
  }
  const note = noteOf(formData, errors, false);
  if (Object.keys(errors).length > 0) return failed(errors);
  return {
    ok: true,
    value: {
      ruleKey,
      newRule,
      edits: content.changed === 0 ? null : content.fields,
      citations,
      relations,
      note,
    },
  };
}

function isDecision(value: string): value is ReviewDecision {
  return value === "approve" || value === "return" || value === "reject";
}

function isRejectReason(value: string): value is RuleRejectReason {
  return (RULE_REJECT_REASONS as readonly string[]).includes(value);
}

/**
 * A decision: approve (optionally tagging the version high impact first), or return or reject
 * with a note; a candidate task's rejection names its reason.
 */
export function parseDecision(
  formData: FormData,
  candidateTask: boolean,
): Parsed<TaskDecisionInput> {
  const errors: FormErrors = {};
  const decision = text(formData, DECIDE_FIELDS.decision);
  if (!isDecision(decision)) return failed({}, [t("workbench.error.decision")]);
  const note = noteOf(formData, errors, decision !== "approve");
  const reasonText = text(formData, DECIDE_FIELDS.reason);
  let reason: RuleRejectReason | null = null;
  if (decision === "reject" && candidateTask) {
    if (isRejectReason(reasonText)) reason = reasonText;
    else add(errors, DECIDE_FIELDS.reason, t("workbench.error.reason"));
  }
  if (Object.keys(errors).length > 0) return failed(errors);
  return {
    ok: true,
    value: {
      decision,
      note,
      highImpact: decision === "approve" && text(formData, DECIDE_FIELDS.highImpact) === "on",
      reason,
    },
  };
}

/** The task a queue row's claim names, lower-cased; null when it is not an id. */
export function parseClaim(formData: FormData): string | null {
  const taskId = text(formData, CLAIM_FIELD).trim().toLowerCase();
  return isHexUuid(taskId) ? taskId : null;
}
