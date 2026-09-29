"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import { Button, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type OpenDocumentAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface OpenDocumentFormProps {
  action: OpenDocumentAction;
  /** The form field's name (the model's OPEN_FIELDS.documentId). */
  field: string;
}

interface Attempt {
  state: ActionState;
  submitted: string;
  count: number;
}

/**
 * Opens one rulebook document by its id or its sha256. A success moves to the viewer; a refusal
 * keeps what was typed, shows why under the field (a malformed id, an id the rulebook does not
 * hold) and moves focus back to the field, or shows the service's problem with its reference.
 */
export function OpenDocumentForm({ action, field }: OpenDocumentFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      submitted: String(formData.get(field) ?? ""),
      count: previous.count + 1,
    }),
    { state: idleAction(), submitted: "", count: 0 },
  );
  const { state } = attempt;
  const inputRef = useRef<HTMLInputElement>(null);
  const problemRef = useRef<HTMLDivElement>(null);
  const error = fieldErrorOf(state, field);
  const problem = state.status === "error" ? state.problem : undefined;

  useEffect(() => {
    if (attempt.count === 0 || attempt.state.status !== "error") return;
    if (attempt.state.problem !== undefined) problemRef.current?.focus();
    else inputRef.current?.focus();
  }, [attempt]);

  return (
    <div data-slot="open-document" className="flex max-w-2xl flex-col gap-4">
      <form
        action={formAction}
        noValidate
        aria-label={t("documents.open.formLabel")}
        className="flex flex-col gap-4"
      >
        <Field
          key={attempt.count}
          id={`${id}-document`}
          label={t("documents.open.label")}
          description={t("documents.open.help")}
          error={error}
          required
        >
          <Input
            ref={inputRef}
            name={field}
            defaultValue={state.status === "error" ? attempt.submitted : ""}
            autoComplete="off"
            spellCheck={false}
            maxLength={80}
            className="font-mono"
          />
        </Field>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("documents.open.pending") : t("documents.open.submit")}
          </Button>
        </div>
      </form>
      <div ref={problemRef} tabIndex={-1} className="outline-none">
        {problem === undefined ? null : (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        )}
      </div>
    </div>
  );
}
