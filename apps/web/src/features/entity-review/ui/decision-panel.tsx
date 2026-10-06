"use client";

import type { Route } from "next";
import Link from "next/link";
import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  KeyValue,
  Label,
  RadioGroup,
  RadioGroupItem,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import {
  ENTITY_REJECT_REASONS,
  MENTION_DECISIONS,
  type EntityRejectReason,
  type MentionDecision,
} from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction, type ActionState } from "@/shared/lib/action-state";
import {
  DECISION_FIELDS,
  GROUP_ITEMS_MAX,
  NOTE_MAX_LENGTH,
  decisionHelp,
  decisionLabel,
  isCapped,
  rejectReasonLabel,
  type DecisionResult,
  type ItemRow,
} from "./decision-shared";
import { ItemsTable } from "./items-table";

export type DecideAction = (
  state: ActionState<DecisionResult>,
  formData: FormData,
) => Promise<ActionState<DecisionResult>>;

export interface DecisionPanelProps {
  /** The decision action, bound to the group's type and name. */
  action: DecideAction;
  items: readonly ItemRow[];
  typeLabel: string;
  nameLabel: string;
  /** The canonical entities tool for this name, to find an entity's id; null for an empty name. */
  resolveHref: string | null;
  queueHref: string;
  /**
   * False when the name cannot name an entity (empty, or a section or rule without its statute):
   * the group cannot make an entity, and a decision names the mentions it covers.
   */
  nameable: boolean;
}

/**
 * The line under the mentions: what the decision covers as things stand. A list of the
 * rulebook's first 200 may leave more open mentions unlisted, and the whole group covers them too.
 */
function scopeOf(selected: number, listed: number): string {
  if (selected > 0) return t("entityReview.scope.selected", { count: selected });
  return isCapped(listed)
    ? t("entityReview.scope.groupCapped", { max: GROUP_ITEMS_MAX })
    : t("entityReview.scope.group", { count: listed });
}

/** The same, as a phrase inside the dialog's sentence. */
function scopePhrase(selected: number, listed: number): string {
  if (selected > 0) return t("entityReview.scope.selectedPhrase", { count: selected });
  return isCapped(listed)
    ? t("entityReview.scope.groupPhraseCapped", { max: GROUP_ITEMS_MAX })
    : t("entityReview.scope.groupPhrase", { count: listed });
}

/** The rulebook's answer to a decision: its status, how the name resolved, the entity, counts. */
function DecidedOutcome({ result }: { result: Extract<DecisionResult, { kind: "decided" }> }) {
  return (
    <div role="status" className="flex flex-col gap-3" data-slot="decision-done">
      <p className="text-sm font-medium text-fg">{result.message}</p>
      <KeyValue
        items={[
          { key: "status", label: t("entityReview.result.status"), value: result.statusLabel },
          ...(result.resolutionLabel === null
            ? []
            : [
                {
                  key: "resolution",
                  label: t("entityReview.result.resolution"),
                  value: result.resolutionLabel,
                },
              ]),
          ...(result.entityId === null || result.entityHref === null
            ? []
            : [
                {
                  key: "entity",
                  label: t("entityReview.result.entity"),
                  value: (
                    <Link
                      href={result.entityHref as Route}
                      className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                    >
                      {result.entityId}
                    </Link>
                  ),
                },
              ]),
          {
            key: "closed",
            label: t("entityReview.result.itemsClosed"),
            value: String(result.itemsClosed),
          },
          {
            key: "targets",
            label: t("entityReview.result.relationTargets"),
            value: String(result.relationTargetsUpdated),
          },
        ]}
      />
    </div>
  );
}

/**
 * Deciding a group: the decision (make the entity, add the name to an entity, or reject the
 * mentions), what it needs (the entity's id, a reason), an optional note, and the mentions it
 * covers (the checked ones, or every open mention of the group), confirmed in a dialog that says
 * what the rulebook records. The one who decided is the signed-in user, set on the server; the
 * form names nobody. The panel stays on the page after the last mention is decided, so the
 * rulebook's answer is still there to read.
 */
export function DecisionPanel({
  action,
  items,
  typeLabel,
  nameLabel,
  resolveHref,
  queueHref,
  nameable,
}: DecisionPanelProps) {
  const id = useId();
  const [decision, setDecision] = useState<MentionDecision | "">("");
  const [entityId, setEntityId] = useState("");
  const [rejectReason, setRejectReason] = useState<EntityRejectReason | "">("");
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState(0);
  const [state, dispatch, pending] = useActionState(
    async (_previous: ActionState<DecisionResult>, formData: FormData) => {
      const next = await action(idleAction(), formData);
      if (next.status === "ok") {
        // The decided mentions are gone from the page: start the next decision from nothing.
        setSelected(new Set());
        setNote("");
        setEntityId("");
        setRejectReason("");
        setDecision("");
      }
      return next;
    },
    idleAction<DecisionResult>(),
  );
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sent > 0 && !pending) outcomeRef.current?.focus();
  }, [sent, pending]);

  const present = items.filter((item) => selected.has(item.reviewId)).map((item) => item.reviewId);
  const scope = scopeOf(present.length, items.length);
  const ready =
    decision !== "" &&
    (nameable || (decision !== "create_entity" && present.length > 0)) &&
    (decision !== "add_alias" || entityId.trim() !== "") &&
    (decision !== "reject" || rejectReason !== "");

  const toggle = (reviewId: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(reviewId);
      else next.delete(reviewId);
      return next;
    });
  };

  const send = () => {
    if (decision === "") return;
    const formData = new FormData();
    formData.set(DECISION_FIELDS.decision, decision);
    if (decision === "add_alias") formData.set(DECISION_FIELDS.entityId, entityId.trim());
    if (decision === "reject") formData.set(DECISION_FIELDS.rejectReason, rejectReason);
    formData.set(DECISION_FIELDS.note, note.trim());
    for (const reviewId of present) formData.append(DECISION_FIELDS.reviewIds, reviewId);
    setConfirming(false);
    setSent((count) => count + 1);
    startTransition(() => dispatch(formData));
  };

  const phrase = scopePhrase(present.length, items.length);
  const confirmText =
    decision === "create_entity"
      ? t("entityReview.confirm.createEntity", { type: typeLabel, name: nameLabel, scope: phrase })
      : decision === "add_alias"
        ? t("entityReview.confirm.addAlias", {
            name: nameLabel,
            entity: entityId.trim(),
            scope: phrase,
          })
        : decision === "reject" && rejectReason !== ""
          ? t("entityReview.confirm.reject", {
              reason: rejectReasonLabel(rejectReason),
              scope: phrase,
            })
          : "";
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const outcome = state.status === "ok" ? state.value : undefined;
  const decisionError = fieldErrorOf(state, DECISION_FIELDS.decision);
  const reviewIdsError = fieldErrorOf(state, DECISION_FIELDS.reviewIds);

  return (
    <div className="flex flex-col gap-6" data-slot="decision-panel">
      {items.length === 0 ? (
        <EmptyState
          title={t("entityReview.group.emptyTitle")}
          body={t("entityReview.group.emptyBody")}
          action={
            <Link
              href={queueHref as Route}
              className="text-sm text-primary underline-offset-2 hover:underline"
            >
              {t("entityReview.backToQueue")}
            </Link>
          }
        />
      ) : (
        <>
          <ItemsTable
            items={items}
            nameLabel={nameLabel}
            selection={{ selected, onToggle: toggle, disabled: pending }}
          />
          <p className="text-sm text-fg-muted" data-slot="decision-scope" aria-live="polite">
            {nameable ? scope : t("entityReview.notNameable", { count: present.length })}
          </p>
          {reviewIdsError === undefined ? null : (
            <p role="alert" className="text-sm text-danger">
              {reviewIdsError}
            </p>
          )}
          <section aria-labelledby={`${id}-heading`} className="flex flex-col gap-4">
            <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
              {t("entityReview.decide")}
            </h2>
            <div className="flex flex-col gap-3">
              <p id={`${id}-legend`} className="text-sm font-medium text-fg">
                {t("entityReview.decisionLegend")}
              </p>
              <RadioGroup
                value={decision}
                onValueChange={(value) => setDecision(value as MentionDecision)}
                aria-labelledby={`${id}-legend`}
                disabled={pending}
              >
                {MENTION_DECISIONS.map((value) => (
                  <div key={value} className="flex items-start gap-2">
                    <RadioGroupItem
                      value={value}
                      id={`${id}-${value}`}
                      className="mt-0.5"
                      disabled={value === "create_entity" && !nameable}
                    />
                    <div className="flex flex-col gap-0.5">
                      <Label htmlFor={`${id}-${value}`}>{decisionLabel(value)}</Label>
                      <p className="text-xs text-fg-muted">{decisionHelp(value)}</p>
                    </div>
                  </div>
                ))}
              </RadioGroup>
              {decisionError === undefined ? null : (
                <p role="alert" className="text-sm text-danger">
                  {decisionError}
                </p>
              )}
            </div>
            {decision === "add_alias" ? (
              <Field
                id={`${id}-entity`}
                label={t("entityReview.entityId")}
                description={
                  resolveHref === null ? (
                    t("entityReview.entityIdHelp")
                  ) : (
                    <>
                      {t("entityReview.entityIdHelp")}{" "}
                      <Link
                        href={resolveHref as Route}
                        className="text-primary underline underline-offset-2"
                      >
                        {t("entityReview.resolveName")}
                      </Link>
                    </>
                  )
                }
                error={fieldErrorOf(state, DECISION_FIELDS.entityId)}
                required
                className="max-w-md"
              >
                <Input
                  value={entityId}
                  autoComplete="off"
                  spellCheck={false}
                  disabled={pending}
                  onChange={(event) => setEntityId(event.target.value)}
                />
              </Field>
            ) : null}
            {decision === "reject" ? (
              <Field
                id={`${id}-reason`}
                label={t("entityReview.rejectReasonField")}
                error={fieldErrorOf(state, DECISION_FIELDS.rejectReason)}
                required
                className="max-w-md"
              >
                <Select
                  value={rejectReason}
                  placeholder={t("entityReview.rejectReasonPlaceholder")}
                  disabled={pending}
                  onChange={(event) => setRejectReason(event.target.value as EntityRejectReason)}
                  options={ENTITY_REJECT_REASONS.map((value) => ({
                    value,
                    label: rejectReasonLabel(value),
                  }))}
                />
              </Field>
            ) : null}
            <Field
              id={`${id}-note`}
              label={t("entityReview.note")}
              description={t("entityReview.noteHelp", { max: NOTE_MAX_LENGTH })}
              error={fieldErrorOf(state, DECISION_FIELDS.note)}
              className="max-w-prose"
            >
              <Textarea
                value={note}
                maxLength={NOTE_MAX_LENGTH}
                disabled={pending}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
            <div className="flex flex-col gap-1 text-sm text-fg-muted" data-slot="recorded">
              <p className="font-medium text-fg">{t("entityReview.recordedTitle")}</p>
              <p>{t("entityReview.recorded")}</p>
            </div>
            <div>
              <Button
                type="button"
                disabled={!ready || pending}
                aria-busy={pending || undefined}
                onClick={() => setConfirming(true)}
              >
                {t("entityReview.submit")}
              </Button>
            </div>
          </section>
        </>
      )}
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="decision-outcome"
        className="flex flex-col gap-3 outline-none"
      >
        {outcome?.kind === "already" ? (
          <p role="status" className="text-sm font-medium text-fg" data-slot="decision-already">
            {outcome.message}
          </p>
        ) : outcome !== undefined ? (
          <DecidedOutcome result={outcome} />
        ) : state.status === "error" ? (
          <>
            {state.problem === undefined ? null : (
              <ErrorState
                title={state.problem.title}
                detail={state.problem.detail}
                correlationId={state.problem.correlationId || undefined}
              />
            )}
            {formErrors.map((message, index) => (
              <p key={index} role="alert" className="text-sm text-danger">
                {message}
              </p>
            ))}
          </>
        ) : null}
      </div>
      {confirming && decision !== "" ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("entityReview.confirm.title", { name: nameLabel })}
          description={confirmText}
          confirmLabel={t("entityReview.submit")}
          cancelLabel={t("common.cancel")}
          destructive={decision === "reject"}
          pending={pending}
          onConfirm={send}
        />
      ) : null}
    </div>
  );
}
