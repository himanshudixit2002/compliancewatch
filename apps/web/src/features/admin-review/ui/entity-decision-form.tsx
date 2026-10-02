"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import { Button, Field, Input, Select, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type EntityDecisionAction = (
  state: ActionState,
  formData: FormData,
) => Promise<ActionState>;

export interface EntityDecisionFormProps {
  action: EntityDecisionAction;
  entityType: string;
  proposedName: string;
}

const DECISIONS = [
  { value: "create_entity", label: "Create entity" },
  { value: "add_alias", label: "Add alias" },
  { value: "reject", label: "Reject" },
] as const;

const REJECT_REASONS = [
  { value: "not_an_entity", label: "Not an entity" },
  { value: "wrong_type", label: "Wrong entity type" },
  { value: "text_artifact", label: "Text artifact" },
  { value: "out_of_scope", label: "Out of scope" },
] as const;

interface Attempt {
  state: ActionState;
}

export function EntityDecisionForm({ action, entityType, proposedName }: EntityDecisionFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
    }),
    { state: idleAction() },
  );
  const errorRef = useRef<HTMLDivElement>(null);
  const error =
    attempt.state.status === "error"
      ? attempt.state.problem?.title ?? attempt.state.problem?.detail
      : undefined;

  useEffect(() => {
    if (attempt.state.status === "error") errorRef.current?.focus();
  }, [attempt.state]);

  return (
    <form action={formAction} noValidate className="flex flex-col gap-4" data-slot="entity-decision-form">
      <input type="hidden" name="entityType" value={entityType} />
      <input type="hidden" name="proposedName" value={proposedName} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${id}-type`} label={t("review.entityGroup.entityType")}>
          <Input id={`${id}-type`} readOnly value={entityType} className="bg-muted" />
        </Field>
        <Field id={`${id}-name`} label={t("review.entityGroup.proposedName")}>
          <Input id={`${id}-name`} readOnly value={proposedName} className="bg-muted" />
        </Field>
      </div>
      <Field id={`${id}-decision`} label="Decision" required>
        <Select
          id={`${id}-decision`}
          name="decision"
          defaultValue="create_entity"
          options={DECISIONS.map((d) => ({ value: d.value, label: d.label }))}
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-reject`} label="Reject reason">
        <Select
          id={`${id}-reject`}
          name="rejectReason"
          defaultValue="not_an_entity"
          options={REJECT_REASONS.map((r) => ({ value: r.value, label: r.label }))}
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-note`} label={t("review.entityGroup.note")}>
        <Textarea
          id={`${id}-note`}
          name="note"
          defaultValue=""
          rows={2}
          placeholder={t("review.entityGroup.notePlaceholder")}
          maxLength={2000}
        />
      </Field>
      <div>
        <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
          Submit decision
        </Button>
      </div>
      <div ref={errorRef} tabIndex={-1} className="outline-none">
        {error === undefined ? null : (
          <p className="text-sm text-fg-error">{error}</p>
        )}
      </div>
    </form>
  );
}
