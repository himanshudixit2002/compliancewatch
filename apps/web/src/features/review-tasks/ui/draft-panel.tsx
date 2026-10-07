"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import {
  Button,
  Checkbox,
  ErrorState,
  Field,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import { CitationRows } from "./citation-rows";
import { ContentFields } from "./content-fields";
import { isFormField } from "./edit-panel";
import {
  DRAFT_FIELDS,
  EDITS_PREFIX,
  LEVELS,
  LIMITS,
  NOTE_FIELD,
  relationField,
  type DraftForm,
  type EditorOntology,
  type WriteResult,
} from "./form-shared";
import { WriteResultView } from "./write-result";

export interface DraftPanelProps {
  action: WriteAction<WriteResult>;
  /** The form, while the signed-in analyst holds a candidate task not drafted yet. */
  form: DraftForm | null;
  /** Why no version can be drafted here, when none can. */
  blocked: string | null;
  ontology: EditorOntology | null;
}

const LEVEL_KEYS = {
  entity: "workbench.level.entity",
  registration: "workbench.level.registration",
  location: "workbench.level.location",
} as const;

/**
 * Drafting a version from the candidate: the rule it joins (the suggested key, or another rule's,
 * or a new rule with its regulator and level), the proposed content with the analyst's changes
 * (only the changed fields are sent), the citations (the candidate's quotes, or the analyst's
 * own), the document's open relation candidates to take onto the draft (with the version each
 * points at, where its kind needs one), and why. The rulebook checks the whole draft as it checks
 * the seed calendar and lists every problem; nothing is stored until it passes.
 */
export function DraftPanel({ action, form, blocked, ontology }: DraftPanelProps) {
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const [problems, setProblems] = useState(0);
  const [showErrors, setShowErrors] = useState(false);
  const [ruleKey, setRuleKey] = useState(form?.ruleKey ?? "");
  const [newRule, setNewRule] = useState(
    form !== null && form.ruleKey !== "" && !form.suggestedKnown,
  );
  const [regulator, setRegulator] = useState(form?.regulator ?? "");
  const [level, setLevel] = useState("");
  const [mode, setMode] = useState<"candidate" | "own">("candidate");
  const [taken, setTaken] = useState<Record<string, boolean>>({});
  const [targets, setTargets] = useState<Record<string, string>>({});
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  const last = attempt.last;
  const fieldErrors = last.status === "error" ? (last.fieldErrors ?? {}) : {};

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (problems > 0) {
      setShowErrors(true);
      requestAnimationFrame(() => {
        formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
      });
      return;
    }
    send(new FormData(event.currentTarget));
  };

  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="draft-panel"
      className="flex flex-col gap-4"
    >
      <h3 id={`${id}-heading`} className="text-base font-semibold text-fg">
        {t("workbench.draft.heading")}
      </h3>
      {form === null ? (
        <p className="text-sm text-fg-muted" data-slot="draft-blocked">
          {blocked ?? t("workbench.draft.unavailable")}
        </p>
      ) : (
        <form ref={formRef} onSubmit={submit} noValidate className="flex flex-col gap-5">
          <p className="max-w-prose text-sm text-fg-muted">{t("workbench.draft.intro")}</p>
          <fieldset className="flex flex-col gap-3" data-slot="draft-rule">
            <legend className="text-sm font-semibold text-fg">
              {t("workbench.draft.ruleLegend")}
            </legend>
            <Field
              id={`${id}-rule-key`}
              label={t("workbench.draft.ruleKey")}
              description={
                newRule
                  ? t("workbench.draft.ruleKeyNew")
                  : form.ruleKeys.includes(ruleKey)
                    ? t("workbench.draft.ruleKeyKnown")
                    : t("workbench.draft.ruleKeyHelp")
              }
              error={fieldErrors[DRAFT_FIELDS.ruleKey]}
              required
            >
              <Input
                name={DRAFT_FIELDS.ruleKey}
                value={ruleKey}
                list={`${id}-rule-keys`}
                autoComplete="off"
                spellCheck={false}
                maxLength={LIMITS.ruleKey}
                disabled={pending}
                className="font-mono"
                onChange={(event) => setRuleKey(event.target.value)}
              />
            </Field>
            <datalist id={`${id}-rule-keys`}>
              {form.ruleKeys.map((key) => (
                <option key={key} value={key} />
              ))}
            </datalist>
            <div className="flex items-center gap-2">
              <Checkbox
                id={`${id}-new-rule`}
                checked={newRule}
                disabled={pending}
                onCheckedChange={(checked) => setNewRule(checked === true)}
              />
              <Label htmlFor={`${id}-new-rule`}>{t("workbench.draft.newRule")}</Label>
              <input type="hidden" name={DRAFT_FIELDS.newRule} value={newRule ? "on" : ""} />
            </div>
            {newRule ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  id={`${id}-regulator`}
                  label={t("workbench.draft.regulator")}
                  error={fieldErrors[DRAFT_FIELDS.regulator]}
                  required
                >
                  <Input
                    name={DRAFT_FIELDS.regulator}
                    value={regulator}
                    maxLength={LIMITS.regulator}
                    disabled={pending}
                    onChange={(event) => setRegulator(event.target.value)}
                  />
                </Field>
                <Field
                  id={`${id}-level`}
                  label={t("workbench.draft.level")}
                  error={fieldErrors[DRAFT_FIELDS.level]}
                  required
                >
                  <Select
                    name={DRAFT_FIELDS.level}
                    value={level}
                    placeholder={t("workbench.draft.levelChoose")}
                    disabled={pending}
                    onChange={(event) => setLevel(event.target.value)}
                    options={LEVELS.map((value) => ({ value, label: t(LEVEL_KEYS[value]) }))}
                  />
                </Field>
              </div>
            ) : null}
          </fieldset>
          <div key={form.revision} className="flex flex-col gap-5">
            <ContentFields
              idPrefix={`${id}-draft`}
              prefix={EDITS_PREFIX}
              initial={form.initial}
              ontology={ontology}
              disabled={pending}
              errors={fieldErrors}
              showErrors={showErrors}
              onProblems={setProblems}
            />
          </div>
          <fieldset className="flex flex-col gap-3" data-slot="draft-citations">
            <legend className="text-sm font-semibold text-fg">
              {t("workbench.draft.citationsLegend")}
            </legend>
            <RadioGroup
              value={mode}
              onValueChange={(value) => setMode(value === "own" ? "own" : "candidate")}
              aria-label={t("workbench.draft.citationsLegend")}
              disabled={pending}
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="candidate" id={`${id}-cite-candidate`} />
                <Label htmlFor={`${id}-cite-candidate`}>
                  {t("workbench.draft.citeCandidate", { count: form.proposedCitations.length })}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="own" id={`${id}-cite-own`} />
                <Label htmlFor={`${id}-cite-own`}>{t("workbench.draft.citeOwn")}</Label>
              </div>
            </RadioGroup>
            <input type="hidden" name={DRAFT_FIELDS.citationsMode} value={mode} />
            {mode === "candidate" ? (
              form.proposedCitations.length === 0 ? (
                <p className="text-sm text-fg-muted">{t("workbench.candidate.noQuotes")}</p>
              ) : (
                <ul className="flex flex-col gap-2" data-slot="draft-candidate-quotes">
                  {form.proposedCitations.map((citation, index) => (
                    <li key={index} className="text-sm">
                      <span className="text-xs text-fg-muted">
                        {t("workbench.source.clause", { ref: citation.clauseRef })}
                      </span>
                      <blockquote className="border-l-2 border-line-strong pl-3 whitespace-pre-wrap text-fg">
                        {citation.quote}
                      </blockquote>
                    </li>
                  ))}
                </ul>
              )
            ) : (
              <CitationRows
                idPrefix={`${id}-draft`}
                options={form.clauseOptions}
                errors={fieldErrors}
                disabled={pending}
                legend={t("workbench.citations.ownLegend")}
                description={t("workbench.citations.ownHelp")}
              />
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-3" data-slot="draft-relations">
            <legend className="text-sm font-semibold text-fg">
              {t("workbench.draft.relationsLegend")}
            </legend>
            {form.relationsError === null ? null : (
              <ErrorState
                title={form.relationsError.message}
                detail={form.relationsError.problem?.detail ?? undefined}
                correlationId={form.relationsError.requestId || undefined}
              />
            )}
            {form.relations.length === 0 ? (
              <p className="text-sm text-fg-muted">{t("workbench.draft.noRelations")}</p>
            ) : (
              form.relations.map((relation, index) => {
                const checked = taken[relation.candidateId] === true;
                const targetName = relationField(index, "target_rule_version_id");
                return (
                  <div
                    key={relation.candidateId}
                    className="flex flex-col gap-2 rounded-md border bg-surface-raised p-3"
                    data-slot="draft-relation"
                    data-candidate={relation.candidateId}
                  >
                    <div className="flex items-start gap-2">
                      <Checkbox
                        id={`${id}-relation-${index}`}
                        checked={checked}
                        disabled={pending}
                        onCheckedChange={(next) =>
                          setTaken((current) => ({
                            ...current,
                            [relation.candidateId]: next === true,
                          }))
                        }
                      />
                      <Label
                        htmlFor={`${id}-relation-${index}`}
                        className="flex flex-col items-start gap-1"
                      >
                        <span>{relation.label}</span>
                        <span className="text-xs font-normal text-fg-muted">
                          {relation.evidenceQuote}
                        </span>
                      </Label>
                    </div>
                    <input
                      type="hidden"
                      name={relationField(index, "candidate_id")}
                      value={checked ? relation.candidateId : ""}
                    />
                    {checked ? (
                      <Field
                        id={`${id}-relation-${index}-target`}
                        label={t("workbench.draft.relationTarget")}
                        description={
                          relation.needsTarget
                            ? t("workbench.draft.relationTargetRequired")
                            : t("workbench.draft.relationTargetOptional")
                        }
                        error={fieldErrors[targetName]}
                        required={relation.needsTarget}
                      >
                        <Select
                          name={targetName}
                          value={targets[relation.candidateId] ?? ""}
                          disabled={pending || relation.targetOptions.length === 0}
                          onChange={(event) =>
                            setTargets((current) => ({
                              ...current,
                              [relation.candidateId]: event.target.value,
                            }))
                          }
                          options={[
                            {
                              value: "",
                              label: relation.needsTarget
                                ? t("workbench.draft.relationTargetChoose")
                                : t("workbench.draft.relationTargetNone"),
                              disabled: relation.needsTarget,
                            },
                            ...relation.targetOptions,
                          ]}
                        />
                      </Field>
                    ) : null}
                  </div>
                );
              })
            )}
          </fieldset>
          <Field
            id={`${id}-note`}
            label={t("workbench.edit.note")}
            description={t("workbench.edit.noteHelp", { max: LIMITS.note })}
            error={fieldErrors[NOTE_FIELD]}
          >
            <Textarea name={NOTE_FIELD} rows={2} maxLength={LIMITS.note} disabled={pending} />
          </Field>
          <div>
            <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
              {t("workbench.draft.submit")}
            </Button>
          </div>
        </form>
      )}
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="draft-outcome"
        fieldNames={Object.keys(fieldErrors).filter(isFormField)}
        renderValue={(value) => <WriteResultView result={value} />}
      />
    </section>
  );
}
