"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import { Button, Field, Input, Select, Textarea } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type RelationDecisionAction = (
  state: ActionState,
  formData: FormData,
) => Promise<ActionState>;

export interface RelationDecisionFormProps {
  action: RelationDecisionAction;
  candidateId: string;
  relation: string;
  evidenceQuote: string;
}

const ACTIONS = [
  { value: "approve", label: "Approve" },
  { value: "reject", label: "Reject" },
] as const;

const REJECT_REASONS = [
  { value: "wrong_kind", label: "Wrong relation kind" },
  { value: "wrong_target", label: "Wrong target" },
  { value: "not_in_text", label: "Not supported by text" },
  { value: "duplicate", label: "Duplicate" },
  { value: "out_of_scope", label: "Out of scope" },
] as const;

interface Attempt {
  state: ActionState;
}

export function RelationDecisionForm({
  action,
  candidateId,
  relation,
  evidenceQuote,
}: RelationDecisionFormProps) {
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
    <form action={formAction} noValidate className="flex flex-col gap-4" data-slot="relation-decision-form">
      <input type="hidden" name="candidateId" value={candidateId} />
      <Field id={`${id}-action`} label="Action" required>
        <Select
          id={`${id}-action`}
          name="action"
          defaultValue="approve"
          options={ACTIONS.map((a) => ({ value: a.value, label: a.label }))}
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-relation`} label="Relation">
        <Input id={`${id}-relation`} readOnly value={relation} className="bg-muted" />
      </Field>
      <Field id={`${id}-quote`} label="Evidence">
        <p className="text-sm text-fg-muted line-clamp-3">{evidenceQuote}</p>
      </Field>
      <Field id={`${id}-from`} label="From rule version" required>
        <Input
          id={`${id}-from`}
          name="fromRuleVersionId"
          defaultValue=""
          placeholder="e.g. v1.0"
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-target`} label="Target rule version (optional)">
        <Input
          id={`${id}-target`}
          name="targetRuleVersionId"
          defaultValue=""
          placeholder="Optional"
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-reject`} label="Reject reason">
        <Select
          id={`${id}-reject`}
          name="rejectReason"
          defaultValue="wrong_kind"
          options={REJECT_REASONS.map((r) => ({ value: r.value, label: r.label }))}
          className="max-w-xs"
        />
      </Field>
      <Field id={`${id}-note`} label={t("review.relation.note")}>
        <Textarea
          id={`${id}-note`}
          name="note"
          defaultValue=""
          rows={2}
          placeholder={t("review.relation.notePlaceholder")}
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