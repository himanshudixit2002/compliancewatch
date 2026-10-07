"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { Button, Field, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import { CitationRows } from "./citation-rows";
import { ContentFields } from "./content-fields";
import {
  LIMITS,
  NOTE_FIELD,
  type EditForm,
  type EditorOntology,
  type WriteResult,
} from "./form-shared";
import { WriteResultView } from "./write-result";

export interface EditPanelProps {
  action: WriteAction<WriteResult>;
  /** The form, while the signed-in analyst may edit the draft; null otherwise. */
  form: EditForm | null;
  /** Why the draft cannot be edited here, when it cannot. */
  blocked: string | null;
  ontology: EditorOntology | null;
}

/** Whether an error key belongs to a field this form shows under itself. */
export function isFormField(name: string): boolean {
  return (
    name === NOTE_FIELD ||
    /^(edits\.)?(title|summary|effective_from|effective_to|todo|specification)$/.test(name) ||
    /^(edits\.)?(recurrence|obligation_template)\.[a-z_]+$/.test(name) ||
    /^citations\.\d+\.(clause_id|quote)$/.test(name) ||
    /^(rule_key|new_rule\.regulator|new_rule\.level|relation_candidates)$/.test(name) ||
    /^relation\.[^.]+\.(take|target)$/.test(name)
  );
}

/**
 * Editing a claimed task's draft: its content (only the fields changed are sent, each checked for
 * shape first), citations to add (every quote verified by the rulebook, which stores all of them or
 * none) and a note saying why, which the decision audit keeps. A condition with shape problems is
 * not sent: the problems show on their fields and focus moves to the first. The panel stays when
 * the page renders the saved draft again, so the answer is still there to read.
 */
export function EditPanel({ action, form, blocked, ontology }: EditPanelProps) {
  const id = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const [problems, setProblems] = useState(0);
  const [showErrors, setShowErrors] = useState(false);
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
      data-slot="edit-panel"
      className="flex flex-col gap-4"
    >
      <h3 id={`${id}-heading`} className="text-base font-semibold text-fg">
        {t("workbench.edit.heading")}
      </h3>
      {form === null ? (
        <p className="text-sm text-fg-muted" data-slot="edit-blocked">
          {blocked ?? t("workbench.edit.unavailable")}
        </p>
      ) : (
        <form ref={formRef} onSubmit={submit} noValidate className="flex flex-col gap-5">
          <div key={form.revision} className="flex flex-col gap-5">
            <ContentFields
              idPrefix={`${id}-edit`}
              prefix=""
              initial={form.initial}
              ontology={ontology}
              disabled={pending}
              errors={fieldErrors}
              showErrors={showErrors}
              onProblems={setProblems}
            />
            <CitationRows
              idPrefix={`${id}-edit`}
              options={form.clauseOptions}
              errors={fieldErrors}
              disabled={pending}
              legend={t("workbench.citations.addLegend")}
              description={t("workbench.citations.addHelp")}
            />
            <Field
              id={`${id}-note`}
              label={t("workbench.edit.note")}
              description={t("workbench.edit.noteHelp", { max: LIMITS.note })}
              error={fieldErrors[NOTE_FIELD]}
            >
              <Textarea name={NOTE_FIELD} rows={2} maxLength={LIMITS.note} disabled={pending} />
            </Field>
          </div>
          <div>
            <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
              {t("workbench.edit.submit")}
            </Button>
          </div>
        </form>
      )}
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="edit-outcome"
        fieldNames={Object.keys(fieldErrors).filter(isFormField)}
        renderValue={(value) => <WriteResultView result={value} />}
      />
    </section>
  );
}
